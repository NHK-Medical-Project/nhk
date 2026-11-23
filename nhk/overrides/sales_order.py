"""Sales Order, with the renewal hand-back on cancel replaced.

Only `before_cancel` changes. The fork's version (`sales_order.py:750`) hands a
cancelled renewal back by walking the previous order's rows, which loses a
device swapped in during the rental and re-links one swapped out
(`nhk.api.renewal_cancel`). Everything else is the fork's class unchanged.
"""

from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

from nhk.api.renewal_cancel import hand_back_to_previous_order


class NHKSalesOrder(SalesOrder):
	def before_cancel(self):
		if self.previous_order_id:
			hand_back_to_previous_order(self)
		# Skip the fork's body, keep what is above it.
		return super(SalesOrder, self).before_cancel()
