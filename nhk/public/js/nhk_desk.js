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

frappe.provide("nhk.so_dialogs");

nhk.so_dialogs = {
	ready_for_pickup(row, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Ready for Pickup"),
			fields: [
				{
					fieldname: "technician_name",
					fieldtype: "Link",
					options: "Technician Details",
					label: __("Technician ID"),
					reqd: 1,
					onchange: function () {
						const technicianName = this.value;
						if (technicianName) {
							frappe.call({
								method: "frappe.client.get_value",
								args: {
									doctype: "Technician Details",
									filters: { name: technicianName },
									fieldname: ["mobile_number", "name", "name1"],
								},
								callback: function (response) {
									if (response.message) {
										dialog.set_value("technician_mobile", response.message.mobile_number || "");
										dialog.set_value("technician_id", response.message.name || "");
										dialog.set_value("technician_name1", response.message.name1 || "");
									}
								},
							});
						}
					},
				},
				{
					fieldname: "technician_name1",
					fieldtype: "Data",
					label: __("Technician Name"),
					reqd: 1,
				},
				{
					fieldname: "technician_mobile",
					fieldtype: "Data",
					label: __("Technician Mobile Number"),
					reqd: 1,
				},
				{
					fieldname: "technician_id",
					fieldtype: "Data",
					label: __("Technician Id"),
					hidden: 1,
				},
				{
					fieldname: "technician_category",
					fieldtype: "Link",
					options: "Technician Category",
					label: __("Technician Category"),
					reqd: 1,
				},
				{
					fieldname: "notify_through_whatsapp",
					fieldtype: "Check",
					label: __("Notify through whatsapp"),
					default: 1,
				},
				{
					fieldname: "mobile_no",
					fieldtype: "Data",
					label: __("Mobile No."),
					default: row.customer_mobile_no || "",
					depends_on: "eval:doc.notify_through_whatsapp",
					description: __("Only 10 digits are allowed. Make sure number is on WhatsApp."),
				},
				{
					fieldname: "message",
					fieldtype: "Small Text",
					label: __("Message"),
					default: `Hello Sir/Mam\n\nPatient Name: ${row.customer_name || ""}\nEquipment Name: ${row.item_name || row.item_code || "No items"}\n\nWe have initiated pickup of the above equipment.\nFor any query call/WhatsApp on 8884880013.`,
					depends_on: "eval:doc.notify_through_whatsapp",
				},
				{
					fieldname: "pickup_date",
					fieldtype: "Datetime",
					label: __("Pickup Date"),
					default: frappe.datetime.now_datetime(),
					reqd: 1,
				},
				{
					fieldname: "pickup_reason",
					fieldtype: "Select",
					label: __("Pick Up Reason"),
					options: [
						"Patient recovered",
						"Patient Expired",
						"Purchased Device from Us",
						"Purchased Device from Others",
						"Item Replacement",
						"Other Reason",
					].join("\n"),
					reqd: 1,
				},
				{
					fieldname: "pickup_remark",
					fieldtype: "Small Text",
					label: __("Pick Up Remark"),
					reqd: 1,
				},



			],
			primary_action_label: __("Ready for Pickup"),
			primary_action: (values) => {
				if (values.notify_through_whatsapp && values.mobile_no) {
					const mobile = values.mobile_no.replace(/\D/g, "");
					if (mobile.length !== 10) {
						frappe.msgprint({
							title: __("Invalid Mobile Number"),
							message: __("Please enter a valid 10-digit mobile number."),
							indicator: "red",
						});
						return;
					}
				}
				frappe.call({
					method: "erpnext.selling.doctype.sales_order.sales_order.make_ready_for_pickup",
					args: {
						docname: row.sales_order_id,
						pickup_date: values.pickup_date,
						pickup_reason: values.pickup_reason,
						pickup_remark: values.pickup_remark,
						technician_name: values.technician_name1,
						technician_mobile: values.technician_mobile,
						technician_id: values.technician_id,
						technician_category: values.technician_category,
					},
					freeze: true,
					callback: (r) => {
						if (values.notify_through_whatsapp && values.mobile_no) {
							frappe.call({
								method: "webtoolex_whatsapp.webtoolex_whatsapp.doctype.whatsapp_instance.whatsapp_instance.send_custom_whatsapp_message",
								args: {
									mobile_number: values.mobile_no.replace(/\D/g, ""),
									message: values.message,
								},
							});
						}
						dialog.hide();
						done(__("Sales Order {0} is Ready for Pickup.", [row.sales_order_id]));
					},
				});
			},
		});
		dialog.show();
	},

	make_pickedup(row, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Mark Picked Up: {0}", [row.sales_order_id]),
			fields: [
				{
					fieldname: "pickup_date",
					fieldtype: "Datetime",
					label: __("Pick Up Date and Time"),
					default: frappe.datetime.now_datetime(),
					reqd: 1,
				},
				{
					fieldname: "notify_through_whatsapp",
					fieldtype: "Check",
					label: __("Notify through whatsapp"),
					default: 1,
				},
				{
					fieldname: "mobile_no",
					fieldtype: "Data",
					label: __("Mobile No."),
					default: row.customer_mobile_no || "",
					depends_on: "eval:doc.notify_through_whatsapp",
					description: __("Only 10 digits are allowed. Make sure number is on WhatsApp."),
				},
				{
					fieldname: "message",
					fieldtype: "Small Text",
					label: __("Message"),
					default: `Hello Sir/Mam\n\nPatient Name: ${row.customer_name || ""}\nEquipment Name: ${row.item_name || row.item_code || "No items"}\n\nWe have successfully received the rental equipment at our office. Thank you for returning it on time.\nIf you have any questions, feel free to call/WhatsApp on 8884880013.`,
					depends_on: "eval:doc.notify_through_whatsapp",
				},
			],
			primary_action_label: __("Picked Up"),
			primary_action: (values) => {
				if (values.notify_through_whatsapp && values.mobile_no) {
					const mobile = values.mobile_no.replace(/\D/g, "");
					if (mobile.length !== 10) {
						frappe.msgprint({
							title: __("Invalid Mobile Number"),
							message: __("Please enter a valid 10-digit mobile number."),
							indicator: "red",
						});
						return;
					}
				}
				frappe.call({
					method: "erpnext.selling.doctype.sales_order.sales_order.make_pickedup",
					args: {
						docname: row.sales_order_id,
						pickup_date: values.pickup_date,
					},
					freeze: true,
					callback: (r) => {
						if (values.notify_through_whatsapp && values.mobile_no) {
							frappe.call({
								method: "webtoolex_whatsapp.webtoolex_whatsapp.doctype.whatsapp_instance.whatsapp_instance.send_custom_whatsapp_message",
								args: {
									mobile_number: values.mobile_no.replace(/\D/g, ""),
									message: values.message,
								},
							});
						}
						dialog.hide();
						done(__("Sales Order {0} is marked as Picked Up.", [row.sales_order_id]));
					},
				});
			},
		});
		dialog.show();
	},

	make_submitted_to_office(row, done) {
		frappe.confirm(
			__("Are you sure you want to make the status as Submitted To Office for {0}?", [row.sales_order_id]),
			() => {
				const item_codes = row.item_code ? row.item_code.split(",").map((s) => s.trim()).filter(Boolean) : [];
				frappe.call({
					method: "erpnext.selling.doctype.sales_order.sales_order.make_submitted_to_office",
					args: {
						docname: row.sales_order_id,
						item_code: JSON.stringify(item_codes),
						submitted_date: frappe.datetime.now_datetime(),
					},
					freeze: true,
					callback: () => {
						done(__("Sales Order {0} is marked as Submitted To Office.", [row.sales_order_id]));
					},
				});
			}
		);
	},
};

