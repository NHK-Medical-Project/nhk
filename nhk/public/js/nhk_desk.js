// Desk-wide: tell the office user who assigned a visit when the technician
// answers it. The server sends `nhk_visit_response` to that user only
// (`nhk.api.notify.tell_office`); the bell notification is created there too,
// so this is just the pop-up for someone looking at the screen right now.

$(document).on("app_ready", function () {
	frappe.realtime.on("nhk_visit_response", function (data) {
		const rejected = data.response === "Rejected";
		frappe.show_alert(
			{
				message: frappe.utils.escape_html(data.message || ""),
				indicator: rejected ? "red" : "green",
			},
			rejected ? 15 : 8
		);

		// Someone looking at that order sees the visit table catch up.
		const frm = window.cur_frm;
		if (frm && frm.doctype === "Sales Order" && frm.doc.name === data.sales_order && !frm.is_dirty()) {
			window.nhk && nhk.sales_order_visits && nhk.sales_order_visits.render(frm);
		}
	});
});

// The office's Reassign and Reschedule dialogs, shared by the Sales Order's
// visit table and the NHK Technician workspace's Technician Visits block.
// `row` needs name, technician_id, technician_name, scheduled_datetime and slot;
// `done(message)` runs once the server has taken the change.
frappe.provide("nhk.visit_dialogs");

nhk.visit_dialogs = {
	reassign(row, done) {
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
					label: __("Reassign To"), reqd: 1, default: row.reassign_to,
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
						done(r.message.moved
							? __("{0} reassigned to {1}.", [row.name, values.technician_id])
							: __("{0} was already with {1}.", [row.name, values.technician_id]));
					},
				}),
		});
		dialog.show();
	},

	reschedule(row, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Reschedule {0}", [row.name]),
			fields: [
				{
					fieldname: "scheduled_datetime", fieldtype: "Datetime", label: __("New date and time"), reqd: 1,
					default: row.scheduled_datetime
				},
				{
					fieldname: "slot", fieldtype: "Select", label: __("Slot"),
					options: ["", "Morning", "Afternoon", "Evening"].join("\n"), default: row.slot || ""
				},
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
						done(__("{0} rescheduled.", [row.name]));
					},
				}),
		});
		dialog.show();
	},
};
