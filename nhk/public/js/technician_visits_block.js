// The NHK Technician workspace's "Technician Visits" block: open visits by
// Technician Response -- Rejected, Pending, Accepted -- with Reassign and
// Reschedule on each, and the technicians alongside, on or off duty and how
// many open jobs each holds. Data from `nhk.api.office.technician_visits`.
//
// The Custom HTML Block only loads this file and calls `render(root_element)`,
// so the code lives in the app repo, not in a database record. It draws inside
// the block's shadow root; the dialogs open on the page, as any desk dialog.

frappe.provide("nhk.technician_visits_block");

nhk.technician_visits_block = {
	RESPONSES: [
		{ key: "Rejected", color: "red", hint: __("Handed back by the technician. Reassign them.") },
		{ key: "Pending", color: "orange", hint: __("Not accepted by the technician yet.") },
		{ key: "Accepted", color: "green", hint: __("Accepted and on the way.") },
	],
	WINDOWS: [
		{ days: 30, label: __("Last 30 days") },
		{ days: 0, label: __("All open") },
	],

	render(root) {
		const state = { tab: null, days: 30, technician: null, search: "", data: null };
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
				args: { days: state.days },
				callback: (r) => {
					state.data = r.message;
					if (!state.tab) {
						const counts = state.data.counts;
						state.tab = (me.RESPONSES.find((x) => counts[x.key]) || me.RESPONSES[0]).key;
					}
					me.draw($el, state);
				},
			});
		};
		const done = (message) => {
			frappe.show_alert({ message, indicator: "green" });
			load();
		};

		$el.on("click", "[data-tab]", function () {
			state.tab = $(this).attr("data-tab");
			me.draw($el, state);
		});
		$el.on("click", "[data-days]", function () {
			state.days = cint($(this).attr("data-days"));
			load();
		});
		$el.on("click", "[data-technician]", function () {
			const id = $(this).attr("data-technician");
			state.technician = state.technician === id ? null : id;
			me.draw($el, state);
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

		// A technician answering a visit this user assigned: catch up at once.
		// One listener however often the workspace redraws the block.
		if (this._listener) frappe.realtime.off("nhk_visit_response", this._listener);
		this._listener = () => root.host && root.host.isConnected && load();
		frappe.realtime.on("nhk_visit_response", this._listener);
		load();
	},

	draw($el, state) {
		const { counts, technicians, days, limited } = state.data;
		const tabs = this.RESPONSES.map((x) => `
			<button class="nhk-tv-tab ${state.tab === x.key ? "active" : ""}" data-tab="${x.key}">
				<span class="indicator-pill ${x.color}">${__(x.key)}</span>
				<span class="nhk-tv-count">${counts[x.key] || 0}</span>
			</button>`).join("");
		const windows = this.WINDOWS.map((w) => `
			<button class="btn btn-xs ${w.days === days ? "btn-primary" : "btn-default"}" data-days="${w.days}">${w.label}</button>`).join(" ");
		const hint = this.RESPONSES.find((x) => x.key === state.tab).hint;

		$el.html(`
			<div class="nhk-tv-head">
				<div class="nhk-tv-title">${__("Technician Visits")}</div>
				<div class="nhk-tv-tools">
					${windows}
					<button class="btn btn-xs btn-default nhk-tv-refresh">${__("Refresh")}</button>
				</div>
			</div>
			<div class="nhk-tv-tabs">${tabs}</div>
			<div class="nhk-tv-body">
				<div class="nhk-tv-main">
					<div class="nhk-tv-bar">
						<span class="text-muted small">${hint}</span>
						<input class="form-control input-xs nhk-tv-search" placeholder="${__("Search visit, customer, area, item")}"
							value="${frappe.utils.escape_html(state.search)}">
					</div>
					<div class="nhk-tv-filter"></div>
					<div class="nhk-tv-rows"></div>
					${limited ? `<div class="text-muted small">${__("Only the oldest visits are shown here. Narrow them with the search, or choose Last 30 days.")}</div>` : ""}
				</div>
				<div class="nhk-tv-side">
					<div class="nhk-tv-side-title">${__("Technicians")}</div>
					${this.technicians(technicians, state)}
				</div>
			</div>`);
		this.draw_rows($el, state);
	},

	draw_rows($el, state) {
		const query = state.search.trim().toLowerCase();
		const rows = state.data.rows.filter((r) =>
			r.technician_response === state.tab
			&& (!state.technician || r.technician_id === state.technician)
			&& (!query || [r.name, r.customer_name, r.patient_name, r.area, r.item_code, r.sales_order_id, r.technician_name]
				.some((v) => (v || "").toLowerCase().includes(query))));

		const person = state.technician && state.data.technicians.find((t) => t.name === state.technician);
		$el.find(".nhk-tv-filter").html(person ? `
			<span class="nhk-tv-chip" data-technician="${person.name}">
				${__("Showing: {0}", [frappe.utils.escape_html(person.name1 || person.name)])} ✕
			</span>` : "");

		$el.find(".nhk-tv-rows").html(rows.length
			? `<table class="table table-sm nhk-tv-table">
				<thead><tr>
					<th>${__("Visit")}</th><th>${__("Customer")}</th><th>${__("Technician")}</th>
					<th>${__("Scheduled")}</th><th>${__("Stage")}</th><th></th>
				</tr></thead>
				<tbody>${rows.map((r) => this.row(r)).join("")}</tbody>
			</table>`
			: `<div class="nhk-tv-empty">${__("No {0} visits.", [__(state.tab)])}</div>`);
	},

	row(r) {
		const esc = frappe.utils.escape_html;
		const scheduled = r.scheduled_datetime
			? `<span class="${r.past_scheduled ? "text-danger" : ""}">${frappe.datetime.str_to_user(r.scheduled_datetime)}</span>`
			: `<span class="text-muted">${__("Not scheduled")}</span>`;
		const phone = r.technician_mobile_no
			? `<a class="text-muted small" href="tel:${esc(r.technician_mobile_no)}">${esc(r.technician_mobile_no)}</a>` : "";
		const actions = [`<button class="btn btn-xs btn-primary" data-action="reassign" data-visit="${esc(r.name)}">${__("Reassign")}</button>`];
		if (r.technician_response !== "Rejected") {
			actions.push(`<button class="btn btn-xs btn-default" data-action="reschedule" data-visit="${esc(r.name)}">${__("Reschedule")}</button>`);
		}
		// On Rejected and Pending the stage only repeats the tab ("Rejected by
		// Suvam"); the next step says it all. Accepted ones say when, and whether
		// the technician has arrived.
		const stage = r.technician_response === "Accepted"
			? `${esc(r.stage || "")}<div class="text-muted small">${esc(r.next_step || "")}</div>`
			: esc(r.next_step || r.stage || "");
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
			<td>${scheduled}${r.slot ? `<div class="text-muted small">${esc(__(r.slot))}</div>` : ""}</td>
			<td class="nhk-tv-stage">${stage}</td>
			<td class="nhk-tv-actions">${actions.join("")}</td>
		</tr>`;
	},

	// On duty, or holding open jobs. The rest are only a number: the Reassign
	// dialog still offers every technician.
	technicians(all, state) {
		const shown = all.filter((t) => t.on_duty || t.pending || t.accepted);
		const idle = all.length - shown.length;
		return shown.map((t) => this.technician(t, state)).join("")
			+ (idle ? `<div class="text-muted small nhk-tv-idle">${__("{0} more Off duty, with no open visits.", [idle])}</div>` : "");
	},

	technician(t, state) {
		const esc = frappe.utils.escape_html;
		return `<div class="nhk-tv-person ${state.technician === t.name ? "active" : ""}" data-technician="${esc(t.name)}"
				title="${__("Show only {0}'s visits", [esc(t.name1 || t.name)])}">
			<div class="nhk-tv-person-name">
				<span class="indicator ${t.on_duty ? "green" : "gray"}"></span>${esc(t.name1 || t.name)}
			</div>
			<div class="text-muted small">
				${t.on_duty ? __("On duty") : __("Off duty")} · ${__("{0} Pending", [t.pending])} · ${__("{0} Accepted", [t.accepted])}
			</div>
		</div>`;
	},

	STYLE: `
		.nhk-tv { padding: 4px 2px; }
		.nhk-tv-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
		.nhk-tv-title { font-size: var(--text-lg); font-weight: 600; }
		.nhk-tv-tools { display: flex; gap: 6px; align-items: center; }
		.nhk-tv-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
		.nhk-tv-tab { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md); background: var(--card-bg); cursor: pointer; }
		.nhk-tv-tab.active { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary); }
		.nhk-tv-count { font-size: var(--text-2xl); font-weight: 700; }
		.nhk-tv-body { display: flex; gap: 16px; align-items: flex-start; }
		.nhk-tv-main { flex: 1; min-width: 0; overflow-x: auto; }
		.nhk-tv-side { width: 240px; flex-shrink: 0; border-left: 1px solid var(--border-color); padding-left: 12px; }
		.nhk-tv-side-title { font-weight: 600; margin-bottom: 6px; }
		.nhk-tv-bar { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
		.nhk-tv-search { max-width: 260px; }
		.nhk-tv-table td { vertical-align: top; }
		.nhk-tv-stage { min-width: 180px; max-width: 280px; }
		.nhk-tv-actions { width: 1%; }
		.nhk-tv-actions .btn { display: block; width: 100%; margin: 0 0 4px 0; }
		.nhk-tv-table a[href^="/app/technician-visit-entry"] { font-weight: 600; }
		.nhk-tv-empty { padding: 24px; text-align: center; color: var(--text-muted); }
		.nhk-tv-person { padding: 6px 8px; border-radius: var(--border-radius); cursor: pointer; }
		.nhk-tv-person:hover, .nhk-tv-person.active { background: var(--subtle-fg); }
		.nhk-tv-person-name { display: flex; align-items: center; gap: 6px; font-weight: 500; }
		.nhk-tv-idle { padding: 6px 8px; }
		.nhk-tv a { color: var(--text-color); }
		.nhk-tv a.text-muted { color: var(--text-muted); }
		.nhk-tv-chip { display: inline-block; margin-bottom: 8px; padding: 2px 10px; border-radius: 12px;
			background: var(--subtle-fg); cursor: pointer; font-size: var(--text-sm); }
		@media (max-width: 900px) {
			.nhk-tv-body { flex-direction: column; }
			.nhk-tv-side { width: 100%; border-left: 0; padding-left: 0; }
		}
	`,
};
