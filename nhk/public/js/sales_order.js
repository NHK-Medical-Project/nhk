// Sales Order: the order's Technician Visit Entries, run from the order.
//
// The office used to open each visit to see whether the technician had
// accepted, arrived, or attached anything, act on it there, then come back to
// the order. This draws every visit on the order into the order's own
// `custom_technician_visit_entry_html` field, says in plain words what is
// happening and what comes next, and offers every action the visit form had.
// Spec: .scratch/sales-order-controls-visits (issues 02, 03, 04, 07).
//
// The server decides everything shown: `nhk.api.visits.for_sales_order`
// returns each row's `stage`, `next_step`, `progress` and the `actions` the
// viewer may take, and every action's endpoint checks again. This file only
// draws them and opens the dialogs.
//
// Loaded through `doctype_js` in hooks.py, after ERPNext's own sales_order.js.
//
// ERPNext's `Installation Done` / `Service Done` buttons are taken over, not
// removed. Frappe runs this file's `refresh` *before* the ERPNext controller's
// `refresh` adds its buttons, so there is nothing to remove yet. The buttons
// call `this.mark_technician_work_done()` on `frm.cscript`, whose prototype is
// the ERPNext controller; an own property of the same name, set in `setup`,
// replaces what they do and leaves their label, place and visibility alone.
// `nhk/tests/test_visits.py` fails if ERPNext renames the methods.
//
// The rental `DELIVERED` and `Submitted To Office` buttons are taken over the
// same way, but only to ask for the distance first: the ERPNext action then
// runs as before and closes the visit itself. The distance is only *held*
// until then; the order's save applies it, prices the visit and records the
// completion time (`nhk.api.visits.stamp_visits_closed_by_the_order`). If the
// order never moves, the visit is untouched.

frappe.provide("nhk.sales_order_visits");

nhk.sales_order_visits = {
	// The order's own HTML field for this. Created on the site as a Custom Field
	// (no module, no fixture), so another site may not have it -- then the table
	// goes into a section of its own after the items, as it first did.
	FIELD: "custom_technician_visit_entry_html",
	SECTION_CLASS: "nhk-technician-visits",

	// Every action the server can offer, with its label, button style and what
	// it does. The server says which apply; this only knows how to run them.
	ACTIONS: {
		complete: { label: "Complete", primary: true, run: (me, frm, row) => me.complete(frm, row) },
		mark_delivered: {
			label: "Mark Delivered", primary: true,
			run: (me, frm) => frm.cscript.make_delivered(),
		},
		submit_to_office: {
			label: "Submitted To Office", primary: true,
			run: (me, frm) => frm.cscript.make_submitted_to_office(),
		},
		reassign: { label: "Reassign", run: (me, frm, row) => me.reassign(frm, row) },
		reschedule: { label: "Reschedule", run: (me, frm, row) => me.reschedule(frm, row) },
		extra_payment: { label: "Extra Payment", run: (me, frm, row) => me.extra_payment(frm, row) },
	},

	render(frm) {
		const target = this.target(frm);
		if (!target) return;
		if (frm.is_new()) {
			target.show(false);
			return;
		}

		// A form refreshes several times while it settles, and the user can move
		// to another order before the answer arrives. Only the latest request for
		// the order still on screen gets to draw.
		const ticket = (this._ticket = (this._ticket || 0) + 1);
		const docname = frm.doc.name;

		frappe.call({
			method: "nhk.api.visits.for_sales_order",
			args: { sales_order: docname },
			callback: (r) => {
				if (ticket !== this._ticket || frm.doc.name !== docname) return;
				const rows = r.message || [];
				target.$body.data("rows", rows);
				target.show(rows.length || target.is_field);
				target.$body.html(rows.length ? this.table(rows) : this.empty());
			},
		});
	},

	// Where the table goes: the order's HTML field when it has one, otherwise a
	// section after the items. Either way, one click handler per wrapper.
	target(frm) {
		const field = frm.fields_dict[this.FIELD];
		let $body, show, is_field = !!field;

		if (field) {
			$body = field.$wrapper;
			show = () => {};
		} else {
			const $section = this.section(frm);
			if (!$section) return null;
			$body = $section.find(".nhk-visits-body");
			show = (on) => $section.toggleClass("hidden", !on);
		}

		if (!$body.data("nhk-bound")) {
			$body.data("nhk-bound", true);
			$body.on("click", "[data-nhk-action]", (e) => {
				e.preventDefault();
				const $btn = $(e.currentTarget);
				const row = ($body.data("rows") || []).find((r) => r.name === $btn.attr("data-visit"));
				row && this.run(frm, $btn.attr("data-nhk-action"), row);
			});
		}
		return { $body, show, is_field };
	},

	section(frm) {
		const existing = $(frm.layout.wrapper).find(`.${this.SECTION_CLASS}`);
		if (existing.length) return existing;

		const items = frm.fields_dict.items;
		const $anchor = items && items.$wrapper.closest(".form-section");
		if (!$anchor || !$anchor.length) return null;

		const $section = $(`
			<div class="form-section card-section ${this.SECTION_CLASS} hidden">
				<div class="section-body"><div class="nhk-visits-body" style="width: 100%;"></div></div>
			</div>
		`);
		$anchor.after($section);
		return $section;
	},

	run(frm, action, row) {
		// Every action ends by reloading the order, which would drop unsaved edits.
		if (frm.is_dirty()) {
			frappe.msgprint(__("Save the order before changing its technician visits."));
			return;
		}
		if (action === "attachments") return this.attachments(row);
		const spec = this.ACTIONS[action];
		spec && spec.run(this, frm, row);
	},

	// ---- drawing -------------------------------------------------------------

	ensure_styles() {
		if ($("#nhk-visits-style").length) return;
		$(`
			<style id="nhk-visits-style">
				.nhk-visits-card {
					background: var(--card-bg, #ffffff);
					border: 1px solid var(--border-color, #e2e8f0);
					border-radius: 8px;
					overflow: hidden;
					box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
					margin: var(--margin-sm, 8px) 0 var(--margin-md, 15px) 0;
				}
				.nhk-visits-card .nhk-visits-head {
					display: flex;
					align-items: center;
					justify-content: space-between;
					padding: 10px 16px;
					background: var(--bg-light-gray, #f8fafc);
					border-bottom: 1px solid var(--border-color, #e2e8f0);
				}
				.nhk-visits-card .nhk-visits-head-title {
					font-weight: 600;
					font-size: 13px;
					color: var(--heading-color, #1e293b);
					display: flex;
					align-items: center;
					gap: 8px;
				}
				.nhk-visits-table {
					width: 100%;
					margin: 0;
					border-collapse: collapse;
					font-size: var(--text-sm, 12px);
				}
				.nhk-visits-table th {
					background: var(--bg-light-gray, #f8fafc);
					color: var(--text-muted, #64748b);
					font-size: 11px;
					font-weight: 600;
					text-transform: uppercase;
					letter-spacing: 0.5px;
					padding: 10px 14px;
					border-bottom: 1px solid var(--border-color, #e2e8f0);
					white-space: nowrap;
				}
				.nhk-visits-table td {
					padding: 12px 14px;
					border-bottom: 1px solid var(--border-color, #f1f5f9);
					vertical-align: top;
				}
				.nhk-visits-table tbody tr:last-child td {
					border-bottom: none;
				}
				.nhk-visits-table tbody tr:hover {
					background-color: var(--bg-hover-color, #f8fafc);
				}
				.nhk-attachment-thumb {
					display: inline-block;
					width: 40px;
					height: 40px;
					border-radius: 6px;
					overflow: hidden;
					border: 1px solid var(--border-color, #e2e8f0);
					background: var(--bg-light-gray, #f8fafc);
					box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
					transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
					flex-shrink: 0;
				}
				.nhk-attachment-thumb:hover {
					transform: scale(1.08);
					border-color: var(--primary, #1b84ff);
					box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
					z-index: 2;
				}
				.nhk-attachment-file {
					display: inline-flex;
					align-items: center;
					gap: 5px;
					padding: 4px 8px;
					border-radius: 4px;
					border: 1px solid var(--border-color, #e2e8f0);
					background: var(--card-bg, #ffffff);
					font-size: 11px;
					text-decoration: none !important;
					color: var(--text-color, #1f272e);
					box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
					max-width: 140px;
					transition: border-color 0.15s ease;
				}
				.nhk-attachment-file:hover {
					border-color: var(--primary, #1b84ff);
					color: var(--primary, #1b84ff);
				}
			</style>
		`).appendTo("head");
	},

	empty() {
		this.ensure_styles();
		return `
			<div class="nhk-visits-card">
				<div class="nhk-visits-head">
					<div class="nhk-visits-head-title">
						<i class="fa fa-wrench text-muted"></i>
						<span>${__("Technician Visits")}</span>
					</div>
				</div>
				<div style="padding: 24px; text-align: center;" class="text-muted">
					<i class="fa fa-folder-open-o" style="font-size: 20px; margin-bottom: 6px; display: block; opacity: 0.5;"></i>
					${__("No technician visits on this order yet.")}
				</div>
			</div>`;
	},

	table(rows) {
		this.ensure_styles();
		const head = [
			__("Visit"),
			__("Technician"),
			__("Progress"),
			__("Schedule"),
			__("Distance & Pay"),
			__("Attachments"),
			"",
		];
		return `
			<div class="nhk-visits-card">
				<div class="nhk-visits-head">
					<div class="nhk-visits-head-title">
						<i class="fa fa-wrench text-muted"></i>
						<span>${__("Technician Visits")}</span>
						<span class="badge badge-pill badge-primary" style="font-size: 11px; padding: 2px 7px;">${rows.length}</span>
					</div>
				</div>
				<div style="overflow-x: auto;">
					<table class="nhk-visits-table">
						<thead>
							<tr>${head.map((h) => `<th style="white-space: nowrap;">${h}</th>`).join("")}</tr>
						</thead>
						<tbody>${rows.map((row) => this.row(row)).join("")}</tbody>
					</table>
				</div>
			</div>`;
	},

	row(row) {
		const esc = frappe.utils.escape_html;
		const when = (v) => (v ? frappe.datetime.str_to_user(v) : "");
		const technician = row.technician_name || row.technician_id || __("Not assigned");
		const phone = row.technician_mobile_no
			? `<div style="margin-top: 3px;"><a class="text-muted small" href="tel:${esc(row.technician_mobile_no)}" style="display: inline-flex; align-items: center; gap: 4px; text-decoration: none;">
					<i class="fa fa-phone" style="font-size: 10px;"></i> ${esc(row.technician_mobile_no)}</a></div>`
			: "";

		// Schedule column:
		// started_at and completed_at shown if scheduled_datetime and slot are not filled
		let schedule = "";
		if (row.scheduled_datetime || row.slot) {
			const parts = [];
			if (row.scheduled_datetime) {
				parts.push(`<div style="font-weight: 500;"><i class="fa fa-calendar-o text-muted" style="margin-right: 4px;"></i>${when(row.scheduled_datetime)}</div>`);
			}
			if (row.slot) {
				parts.push(`<div class="badge badge-light" style="margin-top: 4px; font-weight: normal; border: 1px solid var(--border-color, #e2e8f0);">${esc(__(row.slot))}</div>`);
			}
			schedule = parts.join("");
		} else if (row.started_at || row.completed_at) {
			const parts = [];
			if (row.started_at) {
				parts.push(`<div class="small" style="margin-bottom: 2px;"><span class="text-muted">${__("Started")}:</span> <span style="font-weight: 500;">${when(row.started_at)}</span></div>`);
			}
			if (row.completed_at) {
				parts.push(`<div class="small"><span class="text-muted">${__("Completed")}:</span> <span style="font-weight: 500;">${when(row.completed_at)}</span></div>`);
			}
			schedule = parts.join("");
		} else {
			schedule = `<span class="text-muted small" style="display: inline-flex; align-items: center; gap: 4px;"><i class="fa fa-clock-o"></i> ${__("Not scheduled")}</span>`;
		}

		const pay = [
			row.charges ? `<div style="font-weight: 600; font-size: 13px;">${format_currency(row.charges)}</div>` : "",
			row.kilometers ? `<div class="text-muted small">${esc(String(row.kilometers))} km</div>` : "",
			row.incentive_amount_to_be_processed && row.incentive_amount_to_be_processed !== row.charges
				? `<div class="text-muted small">${__("Incentive")} ${format_currency(row.incentive_amount_to_be_processed)}</div>`
				: "",
			row.extra_payment
				? `<div class="small text-info" style="margin-top: 2px;">+ ${__("Extra")} ${format_currency(row.extra_payment)}
					<span class="text-muted">(${esc(__(row.extra_payment_reason || ""))})</span></div>`
				: "",
			row.payout_month
				? `<div class="small text-success" style="font-weight: 500; margin-top: 2px;"><i class="fa fa-check-circle-o"></i> ${__("Paid in {0}", [esc(row.payout_month)])}</div>`
				: "",
		].filter(Boolean).join("");

		return `
			<tr>
				<td style="min-width: 140px;">
					<a href="/app/technician-visit-entry/${encodeURIComponent(row.name)}" style="font-weight: 600; font-size: 13px; color: var(--primary, #1b84ff);">${esc(row.name)}</a>
					<div><span class="badge" style="background: var(--bg-light-gray, #e2e8f0); color: var(--text-color, #475569); font-weight: 500; font-size: 10.5px; margin-top: 4px; display: inline-block;">${esc(__(row.type || ""))}</span></div>
				</td>
				<td style="min-width: 130px;">
					<div style="font-weight: 500; font-size: 13px;">${esc(technician)}</div>
					${phone}
				</td>
				<td style="min-width: 250px;">
					${this.progress(row)}
					<div style="margin-top: 6px;">${this.indicator(row.stage, this.stage_colour(row))}</div>
					<div class="small text-muted" style="margin-top: 4px; line-height: 1.3;"><i class="fa fa-arrow-right" style="font-size: 9px; opacity: 0.7;"></i> ${esc(row.next_step || "")}</div>
				</td>
				<td style="min-width: 140px;">${schedule}</td>
				<td style="min-width: 110px;" class="text-right">${pay || `<span class="text-muted small">—</span>`}</td>
				<td style="min-width: 140px;">${this.attachments_cell(row)}</td>
				<td style="min-width: 120px; white-space: nowrap;">${this.buttons(row)}</td>
			</tr>`;
	},

	attachments_cell(row) {
		const esc = frappe.utils.escape_html;
		const list = row.attachments || [];
		if (!list.length) {
			if (row.attachment_count) {
				return `<a href="#" class="small text-muted" data-nhk-action="attachments" data-visit="${esc(row.name)}" style="display: inline-flex; align-items: center; gap: 4px;">
					<i class="fa fa-paperclip"></i> ${__("{0} attachment(s)", [row.attachment_count])}</a>`;
			}
			return `<span class="text-muted small">—</span>`;
		}

		const is_image = (url) => /\.(jpe?g|png|webp|gif|svg)$/i.test(url || "");

		return `
			<div class="nhk-attachments-grid" style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
				${list.map((f) => {
					const url = esc(f.file_url || "");
					const name = esc(f.file_name || f.name || __("Attachment"));
					if (is_image(f.file_url)) {
						return `
							<a href="${url}" target="_blank" rel="noopener" class="nhk-attachment-thumb" title="${name}">
								<img src="${url}" alt="${name}" loading="lazy" style="width: 100%; height: 100%; object-fit: cover; display: block;"
									onerror="this.style.display='none'; if (this.nextElementSibling) this.nextElementSibling.style.display='flex';" />
								<div style="display: none; width: 100%; height: 100%; align-items: center; justify-content: center; font-size: 14px; color: var(--text-muted, #94a3b8);">
									<i class="fa fa-image"></i>
								</div>
							</a>`;
					}
					const is_pdf = /\.pdf$/i.test(f.file_url || "");
					const icon = is_pdf ? "fa-file-pdf-o text-danger" : "fa-file-text-o text-primary";
					return `
						<a href="${url}" target="_blank" rel="noopener" class="nhk-attachment-file" title="${name}">
							<i class="fa ${icon}"></i>
							<span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${name}</span>
						</a>`;
				}).join("")}
			</div>`;
	},

	// Six dots with the step names under them: filled up to where the visit has
	// got, red at "Accepted" when the technician turned it down.
	progress(row) {
		const p = row.progress || { steps: [], reached: 0 };
		return `<div style="display: flex; gap: 4px;">${p.steps
			.map((label, i) => {
				const refused = p.rejected && i === 1;
				const colour = refused ? "var(--red-500)" : i <= p.reached ? "var(--green-500)" : "var(--gray-300)";
				return `<div style="flex: 1; text-align: center; min-width: 38px;" title="${frappe.utils.escape_html(label)}">
						<div style="height: 4px; border-radius: 2px; background: ${colour};"></div>
						<div class="text-muted" style="font-size: 10px; margin-top: 2px;">${frappe.utils.escape_html(label)}</div>
					</div>`;
			})
			.join("")}</div>`;
	},

	buttons(row) {
		const esc = frappe.utils.escape_html;
		return (row.actions || [])
			.filter((a) => this.ACTIONS[a])
			.map((a) => {
				const spec = this.ACTIONS[a];
				return `<button class="btn btn-xs ${spec.primary ? "btn-primary" : "btn-default"}"
						style="margin: 0 4px 4px 0;" data-nhk-action="${esc(a)}" data-visit="${esc(row.name)}">
						${__(spec.label)}</button>`;
			})
			.join("");
	},

	stage_colour(row) {
		if (row.progress && row.progress.rejected) return "red";
		if (row.status === "Assigned") return "orange";
		if (row.status === "Closed") return "gray";
		if (row.payout_month) return "gray";
		return "green";
	},

	// ---- actions -------------------------------------------------------------

	after(frm, message) {
		frappe.show_alert({ message, indicator: "green" });
		frm.reload_doc();
	},

	reassign(frm, row) {
		const current = row.technician_name || row.technician_id || __("nobody");
		const dialog = new frappe.ui.Dialog({
			title: __("Reassign {0}", [row.name]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${frappe.utils.escape_html(__("Currently with {0}.", [current]))}</p>`,
				},
				{
					fieldname: "technician_id", fieldtype: "Link", options: "Technician Details",
					label: __("Reassign To"), reqd: 1,
					get_query: () => ({ filters: { name: ["!=", row.technician_id] } }),
				},
				{
					fieldname: "force", fieldtype: "Check", default: 0,
					label: __("Reassign even though the technician has arrived"),
					description: __("Leave this off unless the server refuses. It closes the current technician's check-in and clears the arrival from the visit."),
				},
			],
			primary_action_label: __("Reassign"),
			primary_action: (values) =>
				frappe.call({
					method: "nhk.api.assignment.reassign_visit",
					args: { visit_id: row.name, technician_id: values.technician_id, force: values.force ? 1 : 0 },
					freeze: true,
					callback: (r) => {
						if (!r.message) return;
						dialog.hide();
						this.after(frm, r.message.moved
							? __("{0} reassigned to {1}.", [row.name, values.technician_id])
							: __("{0} was already with {1}.", [row.name, values.technician_id]));
					},
				}),
		});
		dialog.show();
	},

	reschedule(frm, row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Reschedule {0}", [row.name]),
			fields: [
				{ fieldname: "scheduled_datetime", fieldtype: "Datetime", label: __("New date and time"), reqd: 1,
					default: row.scheduled_datetime },
				{ fieldname: "slot", fieldtype: "Select", label: __("Slot"),
					options: ["", "Morning", "Afternoon", "Evening"].join("\n"), default: row.slot || "" },
			],
			primary_action_label: __("Reschedule"),
			primary_action: (values) =>
				frappe.call({
					method: "nhk.api.visits.reschedule",
					args: { visit_id: row.name, scheduled_datetime: values.scheduled_datetime, slot: values.slot },
					freeze: true,
					callback: (r) => {
						if (!r.message) return;
						dialog.hide();
						this.after(frm, __("{0} rescheduled.", [row.name]));
					},
				}),
		});
		dialog.show();
	},

	// What the technician is owed beyond the visit's charge -- out of station,
	// waiting -- paid with the month's payout. The technician enters it in the
	// app; this is the office correcting it, until the month is processed.
	extra_payment(frm, row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Extra payment for {0}", [row.name]),
			fields: [
				{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"),
					default: row.extra_payment || 0,
					description: __("Set 0 to remove it. Paid with this month's technician payout.") },
				{ fieldname: "reason", fieldtype: "Select", label: __("Reason"),
					options: ["", "Out of Station", "Waiting", "Other"].join("\n"),
					default: row.extra_payment_reason || "",
					depends_on: "eval:doc.amount", mandatory_depends_on: "eval:doc.amount" },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note"),
					default: row.extra_payment_note || "",
					depends_on: "eval:doc.amount", mandatory_depends_on: "eval:doc.reason=='Other'" },
			],
			primary_action_label: __("Save"),
			primary_action: (values) =>
				frappe.call({
					method: "nhk.api.payouts.set_extra_payment",
					args: { visit_id: row.name, amount: values.amount || 0, reason: values.reason, note: values.note },
					freeze: true,
					callback: (r) => {
						if (!r.message) return;
						dialog.hide();
						this.after(frm, __("Extra payment on {0} saved.", [row.name]));
					},
				}),
		});
		dialog.show();
	},

	attachments(row) {
		frappe.call({
			method: "nhk.api.visits.attachments_for_visit",
			args: { visit_id: row.name },
			callback: (r) => {
				const esc = frappe.utils.escape_html;
				const list = (r.message || [])
					.map((f) => `<li><a href="${esc(f.file_url)}" target="_blank" rel="noopener">${esc(f.file_name)}</a>
						<span class="text-muted small">${frappe.datetime.str_to_user(f.creation)}</span></li>`)
					.join("");
				frappe.msgprint({
					title: __("Attachments on {0}", [row.name]),
					message: list ? `<ul style="padding-left: 18px;">${list}</ul>` : __("No attachments."),
				});
			},
		});
	},

	// ---- completing ----------------------------------------------------------

	// What ERPNext's `Installation Done` / `Service Done` buttons do now.
	// `method` is the ERPNext method being shadowed, for the fallback.
	complete_open(frm, visit_type, method) {
		frappe.call({
			method: "nhk.api.visits.for_sales_order",
			args: { sales_order: frm.doc.name },
			callback: (r) => {
				const open = (r.message || []).filter(
					(row) => row.type === visit_type && row.status === "Assigned"
				);
				const completable = open.filter((row) => row.can_complete);

				if (!open.length) {
					// No visit to close -- the app may already have closed it. ERPNext's
					// own action then only moves the order, which is still wanted.
					return Object.getPrototypeOf(frm.cscript)[method].call(frm.cscript);
				}
				if (!completable.length) {
					return frappe.msgprint(__("You do not have permission to complete this visit."));
				}
				if (completable.length > 1) {
					return frappe.msgprint(
						__("This order has {0} open visits. Complete each one from the Technician Visits section.", [
							completable.length,
						])
					);
				}
				this.complete(frm, completable[0]);
			},
		});
	},

	// The distance is what the office used to open the visit to enter: it sets
	// the technician's pay. Asked for here, and checked again by the server.
	complete(frm, row) {
		const technician = row.technician_name || row.technician_id || "";
		const dialog = new frappe.ui.Dialog({
			title: __("Complete {0}", [row.name]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${frappe.utils.escape_html(
						`${__(row.type)} · ${technician}`
					)}</p>`,
				},
				{
					fieldname: "kilometers",
					fieldtype: "Int",
					label: __("Distance travelled (km)"),
					reqd: 1,
					default: row.kilometers > 1 ? row.kilometers : undefined,
					description: __("Whole kilometres. Sets the technician's pay."),
				},
				{
					fieldname: "notes",
					fieldtype: "Small Text",
					label: __("Notes"),
					description: __("Added after anything the technician wrote."),
				},
			],
			primary_action_label: __("Complete"),
			primary_action: (values) => {
				if (!(values.kilometers >= 1)) {
					frappe.msgprint(__("Distance must be at least 1 km."));
					return;
				}
				frappe.call({
					method: "nhk.api.visits.complete_from_sales_order",
					args: { visit_id: row.name, kilometers: values.kilometers, notes: values.notes },
					freeze: true,
					freeze_message: __("Completing {0}...", [row.name]),
					callback: (r) => {
						if (!r.message) return;
						dialog.hide();
						frappe.show_alert({
							message: __("{0} is {1}.", [row.name, __(r.message.status)]),
							indicator: "green",
						});
						frm.reload_doc();
					},
				});
			},
		});
		dialog.show();
	},

	// ---- rental buttons: distance first ---------------------------------------

	// Before ERPNext's DELIVERED / Submitted To Office runs, ask for the distance
	// on every open visit of `visit_type`, and hold it on the server until the
	// order's own save closes the visit.
	// Required: the office knows the distance at the button (decided 2026-09-25).
	// The core only checked a distance was there, and one always is -- `validate`
	// fills in 1.0 -- so deliveries closed at the bottom slab without anyone
	// being asked.
	distance_then(frm, visit_type, method, args) {
		const proceed = () => Object.getPrototypeOf(frm.cscript)[method].apply(frm.cscript, args);

		frappe.call({
			method: "nhk.api.visits.for_sales_order",
			args: { sales_order: frm.doc.name },
			callback: (r) => {
				const open = (r.message || []).filter(
					(row) => row.type === visit_type && row.status === "Assigned"
				);
				if (!open.length) return proceed();

				const fields = open.map((row) => ({
					fieldname: row.name,
					fieldtype: "Int",
					reqd: 1,
					label: __("Distance travelled (km): {0} · {1}", [
						row.name,
						row.technician_name || row.technician_id || "",
					]),
					default: row.kilometers > 1 ? row.kilometers : undefined,
				}));
				fields[fields.length - 1].description = __("Whole kilometres. Sets the technician's pay.");

				frappe.prompt(
					fields,
					(values) => {
						if (open.some((row) => !(values[row.name] >= 1))) {
							frappe.msgprint(__("Distance must be at least 1 km."));
							return;
						}
						// A refusal stops here, before the order moves. Frappe has
						// already shown the server's message; nothing to add.
						this.save_distances(open, values).then(proceed, () => { });
					},
					__("{0} distance", [__(visit_type)]),
					__("Continue")
				);
			},
		});
	},

	// One at a time, so a refusal stops before the order moves. Holding is not
	// saving: a later cancel in ERPNext's own dialog leaves the visit untouched.
	save_distances(rows, values) {
		return rows.reduce(
			(done, row) =>
				done.then(() =>
					frappe.call({
						method: "nhk.api.visits.set_distance",
						args: { visit_id: row.name, kilometers: values[row.name] },
						freeze: true,
					})
				),
			Promise.resolve()
		);
	},

	indicator(label, colour) {
		return `<span class="indicator-pill ${colour}">${frappe.utils.escape_html(__(label || ""))}</span>`;
	},
};

frappe.ui.form.on("Sales Order", {
	// `setup` runs once per form, after ERPNext's script has built `frm.cscript`
	// (frappe/public/js/frappe/form/script_manager.js: the doctype JS is
	// evaluated, then "setup" is triggered).



	setup(frm) {
		const visits = nhk.sales_order_visits;
		frm.cscript.mark_technician_work_done = () =>
			visits.complete_open(frm, "Technician Assignment For Sales", "mark_technician_work_done");
		frm.cscript.mark_technician_work_done_service = () =>
			visits.complete_open(
				frm,
				"Technician Assignment For Service",
				"mark_technician_work_done_service"
			);
		frm.cscript.make_delivered = (...args) =>
			visits.distance_then(frm, "Delivery", "make_delivered", args);
		frm.cscript.make_submitted_to_office = (...args) =>
			visits.distance_then(frm, "Pickup", "make_submitted_to_office", args);
	},

	refresh(frm) {
		nhk.sales_order_visits.render(frm);
	},
});
