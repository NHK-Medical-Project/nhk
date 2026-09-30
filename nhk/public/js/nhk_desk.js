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
