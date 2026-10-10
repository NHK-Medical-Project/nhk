// The NHK Technician workspace's "Technician Visits" block. Two views in one
// row of tabs, so the office acts on all of it from one place:
//
// * **The day's visits**, today by default -- Total, Pending, Accepted,
//   Rejected, Completed -- with the patient's Payment Status and Mode Of
//   Payment on each, and Reassign and Reschedule on the open ones. Data from
//   `nhk.api.office.technician_visits`.
// * **Sleep study pickups**, every study still out with a patient whatever the
//   date -- With Patient, To Assign, Assigned -- with Assign Pickup, Reassign
//   and Reschedule. Data from `nhk.api.office.sleep_study_pickups`. Technicians
//   assign these pickups from the app at night (bench ADR-0006); this is the
//   office's morning view of the result.
//
// The search box and the Technician filter apply to whichever tab is open.
//
// The Custom HTML Block only loads this file and calls `render(root_element)`,
// so the code lives in the app repo, not in a database record. It draws inside
// the block's shadow root; the dialogs open on the page, as any desk dialog.

frappe.provide("nhk.technician_visits_block");

nhk.technician_visits_block = {
	TABS: [
		{ key: "Total", view: "day", color: "blue", hint: __("Every visit of the day.") },
		{ key: "Pending", view: "day", color: "orange", hint: __("Not accepted by the technician yet.") },
		{ key: "Accepted", view: "day", color: "green", hint: __("Accepted and on the way.") },
		{ key: "Rejected", view: "day", color: "red", hint: __("Handed back by the technician. Reassign them.") },
		{ key: "Completed", view: "day", color: "gray", hint: __("Completed on the day.") },
		{ key: "With Patient", view: "sleep", color: "blue", hint: __("Sleep studies delivered, and no pickup arranged yet. Any date.") },
		{ key: "To Assign", view: "sleep", color: "red", hint: __("Sleep studies ready for pickup that no technician has. Assign one.") },
		{ key: "Assigned", view: "sleep", color: "green", hint: __("Sleep study pickups a technician has.") },
	],

	render(root) {
		const state = {
			tab: "Total", date: frappe.datetime.get_today(), search: "", technician: "",
			data: null, sleep: null,
		};
		// Added to the shadow root, not written over it: Frappe put the desk's
		// stylesheet there, and the buttons and links need it.
		const style = document.createElement("style");
		style.textContent = this.STYLE;
		const container = document.createElement("div");
		container.className = "nhk-tv";
		root.append(style, container);
		const $el = $(container);
		const me = this;
		const draw = () => state.data && state.sleep && me.draw($el, state);
		const load_day = () => {
			$el.find(".nhk-tv-refresh").prop("disabled", true);
			frappe.call({
				method: "nhk.api.office.technician_visits",
				args: { date: state.date },
				callback: (r) => {
					state.data = r.message;
					draw();
				},
			});
		};
		const load_sleep = () =>
			frappe.call({
				method: "nhk.api.office.sleep_study_pickups",
				callback: (r) => {
					state.sleep = r.message;
					draw();
				},
			});
		const load = () => {
			load_day();
			load_sleep();
		};
		const go_to = (date) => {
			if (!date) return;
			state.date = date;
			load_day();
		};
		const done = (message) => {
			frappe.show_alert({ message, indicator: "green" });
			load();
		};

		$el.on("click", "[data-tab]", function () {
			state.tab = $(this).attr("data-tab");
			me.draw($el, state);
		});
		$el.on("click", "[data-day]", function () {
			go_to(frappe.datetime.add_days(state.date, cint($(this).attr("data-day"))));
		});
		$el.on("click", ".nhk-tv-today", () => go_to(frappe.datetime.get_today()));
		$el.on("change", ".nhk-tv-date", function () {
			go_to(this.value);
		});
		$el.on("click", ".nhk-tv-refresh", load);
		$el.on("input", ".nhk-tv-search", function () {
			state.search = this.value;
			me.draw_rows($el, state);
		});
		$el.on("change", ".nhk-tv-technician", function () {
			state.technician = this.value;
			me.draw($el, state);
		});
		$el.on("click", "[data-action]", function () {
			const action = $(this).attr("data-action");
			const order = $(this).attr("data-order");
			if (order) {
				const row = state.sleep.rows.find((r) => r.sales_order_id === order);
				if (!row) return;
				if (action === "assign") me.assign_pickup(row, done);
				if (action === "reassign") nhk.visit_dialogs.reassign(row.pickup, done);
				if (action === "reschedule") nhk.visit_dialogs.reschedule(row.pickup, done);
				return;
			}
			const row = state.data.rows.find((r) => r.name === $(this).attr("data-visit"));
			if (!row) return;
			if (action === "reassign") nhk.visit_dialogs.reassign(row, done);
			if (action === "reschedule") nhk.visit_dialogs.reschedule(row, done);
		});

		// A technician answering or collecting on a visit this user assigned:
		// catch up at once. One listener however often the workspace redraws.
		if (this._listener) frappe.realtime.off("nhk_visit_response", this._listener);
		this._listener = () => root.host && root.host.isConnected && load();
		frappe.realtime.on("nhk_visit_response", this._listener);
		load();
	},

	/** Give a sleep study's pickup to a technician (`nhk.api.pickup.assign_pickup_for_order`). */
	assign_pickup(row, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Assign Pickup · {0}", [row.sales_order_id]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${frappe.utils.escape_html(
						__("{0} · {1}, delivered by {2}.", [row.customer_name, row.technician_category, row.delivery_technician_name])
					)}</p>`,
				},
				{ fieldname: "technician_id", fieldtype: "Link", options: "Technician Details", label: __("Technician"), reqd: 1 },
				{
					fieldname: "pickup_date", fieldtype: "Date", label: __("Pickup Date"), reqd: 1,
					default: frappe.datetime.add_days(frappe.datetime.get_today(), 1),
				},
				{
					fieldname: "slot", fieldtype: "Select", label: __("Slot"), reqd: 1,
					options: ["Morning", "Afternoon", "Evening"].join("\n"), default: "Morning",
				},
			],
			primary_action_label: __("Assign"),
			primary_action: (values) =>
				frappe.call({
					method: "nhk.api.pickup.assign_pickup_for_order",
					args: {
						sales_order_id: row.sales_order_id,
						technician_id: values.technician_id,
						pickup_date: values.pickup_date,
						slot: values.slot,
						technician_category: row.technician_category,
					},
					freeze: true,
					callback: (r) => {
						if (!r.message) return;
						dialog.hide();
						done(__("Pickup of {0} assigned to {1}.", [row.sales_order_id, r.message.technician_name || values.technician_id]));
					},
				}),
		});
		dialog.show();
	},

	/** The technician names a row is about, for the Technician filter. */
	technicians_of(row, view) {
		return view === "day"
			? [row.technician_name || row.technician_id]
			: [row.delivery_technician_name || row.delivery_technician_id,
				row.pickup && (row.pickup.technician_name || row.pickup.technician_id)];
	},

	/** Rows of one tab, after the Technician filter but before the search. */
	rows_of(state, tab) {
		const view = this.TABS.find((x) => x.key === tab).view;
		const rows = view === "day"
			? state.data.rows.filter((r) => tab === "Total" || r.group === tab)
			: state.sleep.rows.filter((r) => r.group === tab);
		return state.technician
			? rows.filter((r) => this.technicians_of(r, view).includes(state.technician))
			: rows;
	},

	draw($el, state) {
		const esc = frappe.utils.escape_html;
		const is_today = state.date === frappe.datetime.get_today();
		const tab = (x) => `
			<button class="nhk-tv-tab ${state.tab === x.key ? "active" : ""}" data-tab="${x.key}">
				<span class="indicator-pill ${x.color}">${__(x.key)}</span>
				<span class="nhk-tv-count">${this.rows_of(state, x.key).length}</span>
			</button>`;
		const group = (view, label) => `
			<div class="nhk-tv-group">
				<div class="nhk-tv-group-label">${label}</div>
				<div class="nhk-tv-tabs">${this.TABS.filter((x) => x.view === view).map(tab).join("")}</div>
			</div>`;
		const hint = this.TABS.find((x) => x.key === state.tab).hint;

		const names = new Set();
		state.data.rows.forEach((r) => this.technicians_of(r, "day").forEach((n) => n && names.add(n)));
		state.sleep.rows.forEach((r) => this.technicians_of(r, "sleep").forEach((n) => n && names.add(n)));
		const options = [...names].sort((a, b) => a.localeCompare(b)).map((n) =>
			`<option value="${esc(n)}" ${n === state.technician ? "selected" : ""}>${esc(n)}</option>`).join("");

		$el.html(`
			<div class="nhk-tv-head">
				<div class="nhk-tv-title">${__("Technician Visits")}</div>
				<div class="nhk-tv-tools">
					<button class="btn btn-xs btn-default" data-day="-1" title="${__("Previous day")}">‹</button>
					<input type="date" class="form-control input-xs nhk-tv-date" value="${state.date}">
					<button class="btn btn-xs btn-default" data-day="1" title="${__("Next day")}">›</button>
					<button class="btn btn-xs ${is_today ? "btn-primary" : "btn-default"} nhk-tv-today">${__("Today")}</button>
					<button class="btn btn-xs btn-default nhk-tv-refresh">${__("Refresh")}</button>
				</div>
			</div>
			<div class="nhk-tv-groups">
				${group("day", __("Visits on {0}", [frappe.datetime.str_to_user(state.date)]))}
				${group("sleep", __("Sleep study pickups · all open"))}
			</div>
			<div class="nhk-tv-bar">
				<span class="text-muted small">${hint}</span>
				<div class="nhk-tv-filters">
					<select class="form-control input-xs nhk-tv-technician">
						<option value="">${__("All technicians")}</option>${options}
					</select>
					<input class="form-control input-xs nhk-tv-search" placeholder="${__("Search visit, order, customer, area, item")}"
						value="${esc(state.search)}">
				</div>
			</div>
			<div class="nhk-tv-rows"></div>`);
		this.draw_rows($el, state);
	},

	draw_rows($el, state) {
		const view = this.TABS.find((x) => x.key === state.tab).view;
		const query = state.search.trim().toLowerCase();
		const fields = view === "day"
			? (r) => [r.name, r.customer_name, r.patient_name, r.area, r.item_code, r.sales_order_id, r.technician_name]
			: (r) => [r.sales_order_id, r.customer_name, r.area, r.technician_category, r.delivery_technician_name,
				r.pickup && r.pickup.name, r.pickup && r.pickup.technician_name];
		const rows = this.rows_of(state, state.tab).filter((r) =>
			!query || fields(r).some((v) => (v || "").toLowerCase().includes(query)));

		if (!rows.length) {
			$el.find(".nhk-tv-rows").html(`<div class="nhk-tv-empty">${view === "sleep"
				? __("No sleep studies here.")
				: state.tab === "Total"
					? __("No visits on {0}.", [frappe.datetime.str_to_user(state.date)])
					: __("No {0} visits on {1}.", [__(state.tab), frappe.datetime.str_to_user(state.date)])}</div>`);
			return;
		}
		const head = view === "day"
			? [__("Visit"), __("Customer"), __("Technician"), __("Stage"), __("Payment Status"), __("Mode Of Payment"), ""]
			: [__("Order"), __("Study"), __("Delivered"), __("Pickup"), ""];
		$el.find(".nhk-tv-rows").html(`<table class="table table-sm nhk-tv-table">
			<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
			<tbody>${rows.map((r) => (view === "day" ? this.row(r) : this.sleep_row(r))).join("")}</tbody>
		</table>`);
	},

	row(r) {
		const esc = frappe.utils.escape_html;
		const phone = r.technician_mobile_no
			? `<a class="text-muted small" href="tel:${esc(r.technician_mobile_no)}">${esc(r.technician_mobile_no)}</a>` : "";
		const open = r.group !== "Completed";
		const actions = [];
		if (open) {
			actions.push(`<button class="btn btn-xs btn-primary" data-action="reassign" data-visit="${esc(r.name)}">${__("Reassign")}</button>`);
			if (r.group !== "Rejected") {
				actions.push(`<button class="btn btn-xs btn-default" data-action="reschedule" data-visit="${esc(r.name)}">${__("Reschedule")}</button>`);
			}
		}
		// Completed: the stage says when. Accepted: when, and whether the
		// technician has arrived. Pending and Rejected: the next step says it all
		// -- the stage only repeats the tab ("Rejected by Suvam").
		const stage = r.group === "Completed"
			? esc(r.stage || "")
			: r.group === "Accepted"
				? `${esc(r.stage || "")}<div class="text-muted small">${esc(r.next_step || "")}</div>`
				: esc(r.next_step || r.stage || "");
		const paid = r.payment_status === "Paid";
		const payment = r.payment_status
			? `<span class="indicator-pill ${paid ? "green" : "orange"}">${__(r.payment_status)}</span>
				${!paid && r.reason_for_payment_pending
					? `<div class="text-muted small">${esc(r.reason_for_payment_pending)}</div>` : ""}`
			: `<span class="text-muted">—</span>`;
		const modes = (r.payments || []).length
			? r.payments.map((p) => `<div>${esc(p.mode_of_payment || "")} ${format_currency(p.amount)}
				<span class="text-muted small">· ${esc(__(p.status))}</span></div>`).join("")
			: `<span class="text-muted">—</span>`;

		return `<tr>
			<td>
				<a href="/app/technician-visit-entry/${encodeURIComponent(r.name)}">${esc(r.name)}</a>
				<div class="text-muted small">${esc(__(r.type || ""))}${r.item_code ? " · " + esc(r.item_code) : ""}</div>
			</td>
			<td>
				${esc(r.customer_name || r.patient_name || "")}
				<div class="small">
					<a class="text-muted" href="/app/sales-order/${encodeURIComponent(r.sales_order_id || "")}">${esc(r.sales_order_id || "")}</a>
					${r.area ? `<span class="text-muted"> · ${esc(r.area)}</span>` : ""}
				</div>
			</td>
			<td>${esc(r.technician_name || r.technician_id || "")}<div>${phone}</div></td>
			<td class="nhk-tv-stage">${stage}</td>
			<td>${payment}</td>
			<td class="nhk-tv-mode">${modes}</td>
			<td class="nhk-tv-actions">${actions.join("")}</td>
		</tr>`;
	},

	sleep_row(r) {
		const esc = frappe.utils.escape_html;
		const p = r.pickup;
		const nights = r.delivered_at
			? frappe.datetime.get_day_diff(frappe.datetime.get_today(), r.delivered_at.slice(0, 10)) : null;
		const out = nights === null ? "" : nights === 0 ? __("today") : nights === 1 ? __("1 night out") : __("{0} nights out", [nights]);

		let pickup = `<span class="text-muted">${r.order_status === "Ready for Pickup" ? __("Left to the office") : "—"}</span>`;
		if (p) {
			const answer = { Accepted: "green", Rejected: "red", Pending: "orange" }[p.technician_response] || "gray";
			const when = p.scheduled_datetime ? frappe.datetime.str_to_user(p.scheduled_datetime.slice(0, 10)) : "";
			pickup = `
				<a href="/app/technician-visit-entry/${encodeURIComponent(p.name)}">${esc(p.technician_name || p.technician_id || "")}</a>
				<span class="indicator-pill ${answer}">${__(p.technician_response)}</span>
				<div class="text-muted small">${esc([when, p.slot ? __(p.slot) : ""].filter(Boolean).join(", "))}${
					p.pickup_arranged_by ? " · " + __("arranged by the delivering technician") : ""}</div>
				${p.technician_response === "Rejected" && p.rejection_reason
					? `<div class="text-muted small">${esc(p.rejection_reason)}</div>` : ""}`;
		}

		const button = (action, label, primary) =>
			`<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"}" data-action="${action}" data-order="${esc(r.sales_order_id)}">${label}</button>`;
		const actions = [];
		if (!p) actions.push(button("assign", __("Assign Pickup"), r.group === "To Assign"));
		if (p) {
			actions.push(button("reassign", __("Reassign"), p.technician_response === "Rejected"));
			if (p.technician_response !== "Rejected") actions.push(button("reschedule", __("Reschedule")));
		}

		return `<tr>
			<td>
				<a href="/app/sales-order/${encodeURIComponent(r.sales_order_id)}">${esc(r.sales_order_id)}</a>
				<div>${esc(r.customer_name || "")}${r.area ? `<span class="text-muted small"> · ${esc(r.area)}</span>` : ""}</div>
			</td>
			<td>${esc(__(r.technician_category || ""))}</td>
			<td>
				${esc(r.delivery_technician_name || r.delivery_technician_id || "")}
				<div class="text-muted small">${r.delivered_at ? esc(frappe.datetime.str_to_user(r.delivered_at.slice(0, 10))) : ""}${out ? " · " + esc(out) : ""}</div>
			</td>
			<td class="nhk-tv-stage">${pickup}</td>
			<td class="nhk-tv-actions">${actions.join("")}</td>
		</tr>`;
	},

	STYLE: `
		.nhk-tv { padding: 4px 2px; }
		.nhk-tv-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
		.nhk-tv-title { font-size: var(--text-lg); font-weight: 600; }
		.nhk-tv-tools { display: flex; gap: 6px; align-items: center; }
		.nhk-tv-date { width: 150px; }
		.nhk-tv-groups { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 12px; }
		.nhk-tv-group-label { font-size: var(--text-xs); color: var(--text-muted); text-transform: uppercase;
			letter-spacing: 0.04em; margin-bottom: 6px; }
		.nhk-tv-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
		.nhk-tv-tab { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md); background: var(--card-bg); cursor: pointer; }
		.nhk-tv-tab.active { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary); }
		.nhk-tv-count { font-size: var(--text-2xl); font-weight: 700; }
		.nhk-tv-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
		.nhk-tv-filters { display: flex; gap: 6px; }
		.nhk-tv-technician { width: 180px; }
		.nhk-tv-search { width: 280px; }
		.nhk-tv-rows { overflow-x: auto; }
		.nhk-tv-table td { vertical-align: top; }
		.nhk-tv-table a[href^="/app/technician-visit-entry"] { font-weight: 600; }
		.nhk-tv-stage { min-width: 180px; max-width: 300px; }
		.nhk-tv-mode { white-space: nowrap; }
		.nhk-tv-actions { width: 1%; }
		.nhk-tv-actions .btn { display: block; width: 100%; margin: 0 0 4px 0; white-space: nowrap; }
		.nhk-tv-empty { padding: 24px; text-align: center; color: var(--text-muted); }
		.nhk-tv a { color: var(--text-color); }
		.nhk-tv a.text-muted { color: var(--text-muted); }
	`,
};
