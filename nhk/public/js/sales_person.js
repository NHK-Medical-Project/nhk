// Sales Person: the public order form link.
//
// Each sales person has their own link, `/order-form?token=<token>`; a draft
// Sales Order raised from it carries their name (`nhk.api.order_form`). The
// office copies the link from here and sends it to them. New Order Form Link
// replaces the token, so a leaked link stops working. The Sleep Study link is
// the same link opened on the sleep study questions alone (`&form=sleep-study`).

frappe.ui.form.on("Sales Person", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.is_group) return;

		frm.add_custom_button(__("Copy Order Form Link"), () => {
			frappe.call("nhk.api.order_form.form_link", { sales_person: frm.doc.name }).then((r) => {
				frappe.utils.copy_to_clipboard(r.message);
			});
		}, __("Order Form"));

		frm.add_custom_button(__("Copy Sleep Study Form Link"), () => {
			frappe.call("nhk.api.order_form.form_link", { sales_person: frm.doc.name, form: "sleep-study" }).then((r) => {
				frappe.utils.copy_to_clipboard(r.message);
			});
		}, __("Order Form"));

		frm.add_custom_button(__("New Order Form Link"), () => {
			frappe.confirm(
				__("The old link for {0} will stop working. Make a new one?", [frm.doc.name.bold()]),
				() => frappe.call("nhk.api.order_form.new_form_link", { sales_person: frm.doc.name }).then((r) => {
					frm.reload_doc();
					frappe.utils.copy_to_clipboard(r.message);
				})
			);
		}, __("Order Form"));
	},
});
