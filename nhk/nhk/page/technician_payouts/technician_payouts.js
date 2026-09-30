// Technician Payouts: one month of technician pay, the way the office's sheet
// laid it out -- per staff member, Visits, Extra, Sales, Fixed Incentives, Total.
//
// Visits and Extra come from the month's completed visits; Sales and Fixed are
// typed in here. Processing the month freezes it and settles its visits. All
// figures and every rule come from `nhk.api.payouts`; this page draws them.
// Spec: .scratch/technician-monthly-payout.

frappe.pages["technician-payouts"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Technician Payouts"),
		single_column: true,
	});
	wrapper.technician_payouts = new nhk.TechnicianPayouts(page);
};

frappe.pages["technician-payouts"].on_page_show = function (wrapper) {
	wrapper.technician_payouts && wrapper.technician_payouts.load();
};

frappe.provide("nhk");

nhk.TechnicianPayouts = class TechnicianPayouts {
	constructor(page) {
		this.page = page;
		this.dirty = false;
		this.$body = $(`<div class="nhk-payouts" style="padding: var(--padding-md) 0;"></div>`).appendTo(page.main);

		this.month = page.add_field({
			fieldname: "month",
			fieldtype: "Select",
			label: __("Month"),
			options: this.month_options(),
			default: this.last_month(),
			change: () => this.switch_month(),
		});
		this.shown_month = this.month.get_value();

		page.set_secondary_action(__("Save"), () => this.save());
		page.set_primary_action(__("Process Month"), () => this.process());
		page.add_inner_button(__("Add Staff"), () => this.add_staff());

		// Leaving with typed-in incentives unsaved loses them.
		$(window).on("beforeunload.nhk_payouts", () => (this.dirty ? true : undefined));

		this.$body.on("input", "input[data-field]", (e) => this.edited($(e.currentTarget)));
		this.$body.on("click", "[data-technician]", (e) => {
			e.preventDefault();
			this.drill_down($(e.currentTarget).attr("data-technician"));
		});
		// No load here: Frappe fires `on_page_show` straight after `on_page_load`.
	}

	// ---- month ---------------------------------------------------------------

	last_month() {
		return frappe.datetime.add_months(frappe.datetime.get_today(), -1).slice(0, 7);
	}

	// The last 24 months, newest first, labelled like the sheet ("August 2026").
	month_options() {
		const out = [];
		for (let i = 0; i < 24; i++) {
			const d = frappe.datetime.add_months(frappe.datetime.get_today(), -i).slice(0, 7);
			out.push({ value: d, label: this.month_label(d) });
		}
		return out;
	}

	month_label(ym) {
		return moment(ym + "-01").format("MMMM YYYY");
	}

	switch_month() {
		const next = this.month.get_value();
		if (this.dirty && next !== this.shown_month) {
			frappe.confirm(
				__("You have unsaved changes to {0}. Leave them?", [this.month_label(this.shown_month)]),
				() => { this.dirty = false; this.load(); },
				() => this.month.set_value(this.shown_month)
			);
			return;
		}
		this.load();
	}

	// ---- loading and drawing -------------------------------------------------

	load() {
		const month = this.month.get_value();
		frappe.call({
			method: "nhk.api.payouts.month_summary",
			args: { month },
			freeze: true,
			callback: (r) => {
				if (!r.message) return;
				this.shown_month = month;
				this.data = r.message;
				this.dirty = false;
				this.draw();
			},
		});
	}

	draw() {
		const d = this.data;
		const locked = d.processed;
		this.page.btn_primary.toggle(!locked).prop("disabled", !d.can_process);
		this.page.btn_secondary.toggle(!locked);
		this.page.inner_toolbar.find("button").toggle(!locked);

		this.$body.html(`
			${this.banner()}
			<div style="overflow-x: auto;">
				<table class="table table-bordered" style="font-size: var(--text-md); min-width: 720px;">
					<thead>
						<tr><th colspan="6" style="text-align: center; font-size: var(--text-lg);">
							${frappe.utils.escape_html(this.month_label(d.month))}</th></tr>
						<tr>
							<th>${__("Staff Name")}</th>
							<th class="text-right">${__("Visits")}</th>
							<th class="text-right">${__("Extra")}</th>
							<th class="text-right">${__("Sales")}</th>
							<th class="text-right">${__("Fixed Incentives")}</th>
							<th class="text-right">${__("Total")}</th>
						</tr>
					</thead>
					<tbody>
						${d.rows.length ? d.rows.map((r) => this.row(r, locked)).join("") : this.no_rows()}
					</tbody>
					<tfoot>${this.totals_row()}</tfoot>
				</table>
			</div>
		`);
	}

	banner() {
		const d = this.data;
		const esc = frappe.utils.escape_html;
		let html;
		if (d.processed) {
			html = `<div class="alert alert-success">
				${__("Processed on {0} by {1}. These figures are final, and the visits they cover can no longer change.",
				[esc(frappe.datetime.str_to_user(d.processed_on)), esc(d.processed_by || "")])}</div>`;
		} else {
			html = `<div class="alert alert-info">
				${__("Not processed yet. Visits and Extra update as technicians complete jobs; type Sales and Fixed Incentives, then Save.")}
				${d.can_process ? "" : "<br>" + __("This month has not ended, so it cannot be processed yet.")}</div>`;
		}
		if (d.undated_visits) {
			html += `<div class="alert alert-warning">
				${__("{0} completed visit(s) have no completion date and are not in any month. Open them and set the date so they get paid.",
				[d.undated_visits])}</div>`;
		}
		return html;
	}

	no_rows() {
		return `<tr><td colspan="6" class="text-muted text-center">
			${__("No completed visits or incentives this month. Use Add Staff to pay an incentive.")}</td></tr>`;
	}

	row(r, locked) {
		const esc = frappe.utils.escape_html;
		const money = (v) => format_currency(v || 0);
		const count = (n) => (n ? ` <span class="text-muted small">(${n})</span>` : "");
		const input = (field) =>
			locked
				? money(r[field])
				: `<input type="number" min="0" step="1" class="form-control input-sm text-right"
					style="max-width: 130px; margin-left: auto;" data-field="${field}"
					data-row="${esc(r.technician_id)}" value="${flt(r[field]) || ""}" placeholder="0">`;

		return `
			<tr data-row="${esc(r.technician_id)}">
				<td><a href="#" data-technician="${esc(r.technician_id)}" style="font-weight: 600;">
					${esc(r.technician_name || r.technician_id)}</a>
					<div class="text-muted small">${esc(r.technician_id)}</div></td>
				<td class="text-right">${money(r.visit_charges)}${count(r.visit_count)}</td>
				<td class="text-right">${money(r.extra_payments)}${count(r.extra_count)}</td>
				<td class="text-right">${input("sales_incentive")}</td>
				<td class="text-right">${input("fixed_incentive")}</td>
				<td class="text-right" style="font-weight: 600;" data-total>${money(this.row_total(r))}</td>
			</tr>`;
	}

	row_total(r) {
		return flt(r.visit_charges) + flt(r.extra_payments) + flt(r.sales_incentive) + flt(r.fixed_incentive);
	}

	totals_row() {
		const rows = this.data.rows;
		const sum = (f) => rows.reduce((a, r) => a + flt(r[f]), 0);
		const money = (v) => format_currency(v || 0);
		return `
			<tr style="font-weight: 700; background: var(--subtle-fg);">
				<td>${__("TOTAL")}</td>
				<td class="text-right">${money(sum("visit_charges"))}</td>
				<td class="text-right">${money(sum("extra_payments"))}</td>
				<td class="text-right">${money(sum("sales_incentive"))}</td>
				<td class="text-right">${money(sum("fixed_incentive"))}</td>
				<td class="text-right">${money(rows.reduce((a, r) => a + this.row_total(r), 0))}</td>
			</tr>`;
	}

	// Typing an incentive updates the row and the totals straight away; the
	// server recomputes both when it saves.
	edited($input) {
		const r = this.data.rows.find((x) => x.technician_id === $input.attr("data-row"));
		if (!r) return;
		r[$input.attr("data-field")] = flt($input.val());
		this.dirty = true;
		$input.closest("tr").find("[data-total]").html(format_currency(this.row_total(r)));
		this.$body.find("tfoot").html(this.totals_row());
	}

	// ---- actions -------------------------------------------------------------

	rows_to_save() {
		return this.data.rows.map((r) => ({
			technician_id: r.technician_id,
			sales_incentive: flt(r.sales_incentive),
			fixed_incentive: flt(r.fixed_incentive),
		}));
	}

	save() {
		return frappe.call({
			method: "nhk.api.payouts.save_month",
			args: { month: this.data.month, rows: this.rows_to_save() },
			freeze: true,
			callback: (r) => {
				if (!r.message) return;
				this.data = r.message;
				this.dirty = false;
				this.draw();
				frappe.show_alert({ message: __("{0} saved.", [this.month_label(this.data.month)]), indicator: "green" });
			},
		});
	}

	process() {
		const d = this.data;
		const visits = d.rows.reduce((a, r) => a + (r.visit_count || 0), 0);
		frappe.confirm(
			__("Process {0}? This saves {1} as final pay and settles {2} visit(s), which can then no longer change. It cannot be undone here.",
				[this.month_label(d.month), format_currency(d.rows.reduce((a, r) => a + this.row_total(r), 0)), visits]),
			() => {
				// Save what was typed first, so the processed figures include it.
				frappe.call({
					method: "nhk.api.payouts.save_month",
					args: { month: d.month, rows: this.rows_to_save() },
					freeze: true,
					callback: () =>
						frappe.call({
							method: "nhk.api.payouts.process_month",
							args: { month: d.month },
							freeze: true,
							freeze_message: __("Processing {0}...", [this.month_label(d.month)]),
							callback: (r) => {
								if (!r.message) return;
								this.data = r.message;
								this.dirty = false;
								this.draw();
								frappe.show_alert({ message: __("{0} processed.", [this.month_label(d.month)]), indicator: "green" });
							},
						}),
				});
			}
		);
	}

	// Staff paid only a sales or fixed incentive this month have no visits, so
	// they are not listed until added.
	add_staff() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add staff to {0}", [this.month_label(this.data.month)]),
			fields: [
				{
					fieldname: "technician_id", fieldtype: "Link", options: "Technician Details", label: __("Staff"), reqd: 1,
					get_query: () => ({ filters: { name: ["not in", this.data.rows.map((r) => r.technician_id)] } }),
					description: __("Only people with a Technician Details record can be paid here.")
				},
			],
			primary_action_label: __("Add"),
			primary_action: ({ technician_id }) => {
				frappe.db.get_value("Technician Details", technician_id, "name1").then(({ message }) => {
					this.data.rows.push({
						technician_id, technician_name: (message && message.name1) || technician_id,
						visit_count: 0, visit_charges: 0, extra_count: 0, extra_payments: 0,
						sales_incentive: 0, fixed_incentive: 0,
					});
					this.dirty = true;
					dialog.hide();
					this.draw();
				});
			},
		});
		dialog.show();
	}

	drill_down(technician_id) {
		const r = this.data.rows.find((x) => x.technician_id === technician_id);
		frappe.call({
			method: "nhk.api.payouts.technician_month",
			args: { month: this.data.month, technician_id },
			callback: ({ message }) => {
				const esc = frappe.utils.escape_html;
				const visits = message || [];
				const body = visits.length
					? `<div style="overflow-x: auto;"><table class="table table-bordered table-sm" style="font-size: var(--text-sm);">
						<thead><tr><th>${__("Completed")}</th><th>${__("Visit")}</th><th>${__("Type")}</th>
							<th>${__("Order")}</th><th class="text-right">${__("Km")}</th>
							<th class="text-right">${__("Charge")}</th><th class="text-right">${__("Extra")}</th></tr></thead>
						<tbody>${visits.map((v) => `<tr>
							<td>${esc(frappe.datetime.str_to_user(v.completed_on) || "")}</td>
							<td><a href="/app/technician-visit-entry/${encodeURIComponent(v.name)}" target="_blank">${esc(v.name)}</a></td>
							<td>${esc(__(v.type || ""))}</td>
							<td>${v.sales_order_id ? `<a href="/app/sales-order/${encodeURIComponent(v.sales_order_id)}" target="_blank">${esc(v.sales_order_id)}</a>` : ""}</td>
							<td class="text-right">${esc(String(v.kilometers || ""))}</td>
							<td class="text-right">${format_currency(v.charges || 0)}</td>
							<td class="text-right">${v.extra_payment ? `${format_currency(v.extra_payment)}
								<div class="text-muted small">${esc(__(v.extra_payment_reason || ""))}${v.extra_payment_note ? ": " + esc(v.extra_payment_note) : ""}</div>` : ""}</td>
						</tr>`).join("")}</tbody></table></div>`
					: `<p class="text-muted">${__("No visits this month; paid incentives only.")}</p>`;
				frappe.msgprint({
					title: __("{0}: {1}", [(r && r.technician_name) || technician_id, this.month_label(this.data.month)]),
					message: body,
					wide: true,
				});
			},
		});
	}
};
