// One month's Sales Orders by kind, person by person: each sales person and each
// doctor (Referrer), one row each with the kinds as columns. Amounts are order amounts: the security deposit is never
// included. Click a count to list its orders.
const NHK_SPD_METHOD =
	"nhk.nhk.report.sales_person_doctor_monthly.sales_person_doctor_monthly.orders";

// Count column -> the kind of order it counts (`kind_key` on the server).
const NHK_SPD_KINDS = {
	order_count: "Order",
	rental_count: "Rental",
	sleep_study_count: "Sleep Study",
	service_count: "Service",
	visit_count: "Visit",
	renewal_count: "Renewal",
	total_count: "Total",
};

frappe.query_reports["Sales Person Doctor Monthly"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: moment.months(),
			default: moment.months()[moment().month()],
			reqd: 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: moment().year(),
			reqd: 1,
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "doctor",
			label: __("Doctor"),
			fieldtype: "Link",
			options: "Referrer",
		},
		{
			fieldname: "role",
			label: __("Show"),
			fieldtype: "Select",
			options: ["Sales Person and Doctor", "Sales Person", "Doctor"],
			default: "Sales Person and Doctor",
			description: __("Used when no Sales Person or Doctor is chosen"),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const kind = NHK_SPD_KINDS[column.fieldname];
		if (data && kind && data.role_key && data[column.fieldname]) {
			value = `<a class="nhk-spd-count" href="#"
				data-role="${frappe.utils.escape_html(data.role_key)}"
				data-person="${frappe.utils.escape_html(data.person || "")}"
				data-title="${frappe.utils.escape_html(data.label || "")}"
				data-kind="${kind}">${value}</a>`;
		}
		return data && data.bold ? `<b>${value}</b>` : value;
	},

	onload() {
		$(document)
			.off("click.nhk_spd")
			.on("click.nhk_spd", ".nhk-spd-count", function (e) {
				e.preventDefault();
				// attr, not .data(): jQuery would turn an id that looks numeric into a number.
				const $a = $(this);
				nhk_spd_show_orders({
					role: $a.attr("data-role"),
					person: $a.attr("data-person"),
					title: $a.attr("data-title"),
					kind: $a.attr("data-kind"),
				});
			});
	},
};

function nhk_spd_show_orders({ role, person, title, kind }) {
	frappe
		.call(NHK_SPD_METHOD, {
			filters: frappe.query_report.get_filter_values(),
			role,
			person: person || null,
			kind,
		})
		.then(({ message: orders }) => {
			const esc = frappe.utils.escape_html;
			const money = (v) => format_currency(v);
			const sum = (key) => (orders || []).reduce((s, o) => s + flt(o[key]), 0);
			const rows = (orders || [])
				.map(
					(o) => `<tr>
						<td><a href="/app/sales-order/${encodeURIComponent(o.name)}" target="_blank">${esc(o.name)}</a></td>
						<td>${esc(frappe.datetime.str_to_user(o.transaction_date) || "")}</td>
						<td>${esc(o.customer_name || o.customer || "")}</td>
						<td>${esc(__(o.kind))}</td>
						<td>${esc(role === "Doctor" ? o.sales_person || "" : o.custom_referrer_name || o.custom_referrer || "")}</td>
						<td>${esc(o.status || "")}</td>
						<td class="text-right">${money(o.amount)}</td>
						<td class="text-right">${money(o.paid)}</td>
						<td class="text-right">${money(o.unpaid)}</td>
					</tr>`
				)
				.join("");
			const dialog = new frappe.ui.Dialog({
				title: __("{0} ({1}): {2}", [title, __(role), __(kind)]),
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "orders" }],
			});
			dialog.fields_dict.orders.$wrapper.html(`
				<div style="max-height: 65vh; overflow: auto;">
				<table class="table table-bordered table-condensed">
					<thead><tr>
						<th>${__("Sales Order")}</th><th>${__("Date")}</th><th>${__("Customer")}</th>
						<th>${__("Kind")}</th><th>${role === "Doctor" ? __("Sales Person") : __("Doctor")}</th>
						<th>${__("Status")}</th><th class="text-right">${__("Order Amount")}</th>
						<th class="text-right">${__("Paid")}</th><th class="text-right">${__("Unpaid")}</th>
					</tr></thead>
					<tbody>${rows || `<tr><td colspan="9" class="text-muted">${__("No orders")}</td></tr>`}</tbody>
					<tfoot><tr>
						<th colspan="6">${__("Total")} (${(orders || []).length})</th>
						<th class="text-right">${money(sum("amount"))}</th>
						<th class="text-right">${money(sum("paid"))}</th>
						<th class="text-right">${money(sum("unpaid"))}</th>
					</tr></tfoot>
				</table></div>`);
			dialog.show();
		});
}
