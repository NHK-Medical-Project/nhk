// The NHK Technician workspace's "Technician Visits" block: one day's visits,
// today by default -- Total, Pending, Accepted, Rejected, Completed -- with the
// patient's Payment Status and Mode Of Payment on each, and Reassign and
// Reschedule on the open ones. Data from `nhk.api.office.technician_visits`.
//
// The Custom HTML Block only loads this file and calls `render(root_element)`,
// so the code lives in the app repo, not in a database record. It draws inside
// the block's shadow root; the dialogs open on the page, as any desk dialog.

frappe.provide("nhk.technician_visits_block");

nhk.technician_visits_block = {
	TABS: [
		{ key: "Total", color: "blue", hint: __("Every visit of the day.") },
		{ key: "Pending", color: "orange", hint: __("Not accepted by the technician yet.") },
		{ key: "Accepted", color: "green", hint: __("Accepted and on the way.") },
		{ key: "Rejected", color: "red", hint: __("Handed back by the technician. Reassign them.") },
		{ key: "Completed", color: "gray", hint: __("Completed on the day.") },
	],

	render(root) {
		const state = { tab: "Total", date: frappe.datetime.get_today(), search: "", data: null };
		// Added to the shadow root, not written over it: Frappe put the desk's
		// stylesheet there, and the buttons and links need it.
		const style = document.createElement("style");
		style.textContent = this.STYLE;
		const container = document.createElement("div");
		container.className = "nhk-tv";
		root.append(style, container);
		const $el = $(container);
		const me = this;
		const load = () => {
			$el.find(".nhk-tv-refresh").prop("disabled", true);
			frappe.call({
				method: "nhk.api.office.technician_visits",
				args: { date: state.date },
				callback: (r) => {
					state.data = r.message;
					me.draw($el, state);
				},
			});
		};
		const go_to = (date) => {
			if (!date) return;
			state.date = date;
			load();
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
		$el.on("click", "[data-action]", function () {
			const row = state.data.rows.find((r) => r.name === $(this).attr("data-visit"));
			if (!row) return;
			const action = $(this).attr("data-action");
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

	draw($el, state) {
		const { counts } = state.data;
		const is_today = state.date === frappe.datetime.get_today();
		const tabs = this.TABS.map((x) => `
			<button class="nhk-tv-tab ${state.tab === x.key ? "active" : ""}" data-tab="${x.key}">
				<span class="indicator-pill ${x.color}">${__(x.key)}</span>
				<span class="nhk-tv-count">${counts[x.key] || 0}</span>
			</button>`).join("");
		const hint = this.TABS.find((x) => x.key === state.tab).hint;

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
			<div class="nhk-tv-tabs">${tabs}</div>
			<div class="nhk-tv-bar">
				<span class="text-muted small">${hint}</span>
				<input class="form-control input-xs nhk-tv-search" placeholder="${__("Search visit, customer, technician, area, item")}"
					value="${frappe.utils.escape_html(state.search)}">
			</div>
			<div class="nhk-tv-rows"></div>`);
		this.draw_rows($el, state);
	},

	draw_rows($el, state) {
		const query = state.search.trim().toLowerCase();
		const rows = state.data.rows.filter((r) =>
			(state.tab === "Total" || r.group === state.tab)
			&& (!query || [r.name, r.customer_name, r.patient_name, r.area, r.item_code, r.sales_order_id, r.technician_name]
				.some((v) => (v || "").toLowerCase().includes(query))));

		$el.find(".nhk-tv-rows").html(rows.length
			? `<table class="table table-sm nhk-tv-table">
				<thead><tr>
					<th>${__("Visit")}</th><th>${__("Customer")}</th><th>${__("Technician")}</th>
					<th>${__("Stage")}</th><th>${__("Payment Status")}</th><th>${__("Mode Of Payment")}</th><th></th>
				</tr></thead>
				<tbody>${rows.map((r) => this.row(r)).join("")}</tbody>
			</table>`
			: `<div class="nhk-tv-empty">${state.tab === "Total"
				? __("No visits on {0}.", [frappe.datetime.str_to_user(state.date)])
				: __("No {0} visits on {1}.", [__(state.tab), frappe.datetime.str_to_user(state.date)])}</div>`);
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

	STYLE: `
		.nhk-tv { padding: 4px 2px; }
		.nhk-tv-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
		.nhk-tv-title { font-size: var(--text-lg); font-weight: 600; }
		.nhk-tv-tools { display: flex; gap: 6px; align-items: center; }
		.nhk-tv-date { width: 150px; }
		.nhk-tv-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
		.nhk-tv-tab { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md); background: var(--card-bg); cursor: pointer; }
		.nhk-tv-tab.active { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary); }
		.nhk-tv-count { font-size: var(--text-2xl); font-weight: 700; }
		.nhk-tv-bar { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
		.nhk-tv-search { max-width: 300px; }
		.nhk-tv-rows { overflow-x: auto; }
		.nhk-tv-table td { vertical-align: top; }
		.nhk-tv-table a[href^="/app/technician-visit-entry"] { font-weight: 600; }
		.nhk-tv-stage { min-width: 180px; max-width: 300px; }
		.nhk-tv-mode { white-space: nowrap; }
		.nhk-tv-actions { width: 1%; }
		.nhk-tv-actions .btn { display: block; width: 100%; margin: 0 0 4px 0; }
		.nhk-tv-empty { padding: 24px; text-align: center; color: var(--text-muted); }
		.nhk-tv a { color: var(--text-color); }
		.nhk-tv a.text-muted { color: var(--text-muted); }
	`,
};
