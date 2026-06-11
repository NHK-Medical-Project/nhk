import frappe
from frappe.model.document import Document

class TechnicianVisitEntry(Document):
    def on_trash(self):
        # Get technician_id and charges
        technician_id = self.technician_id  # Replace with the actual field name if different
        charges = self.charges  # Replace with the actual field name if different

        if technician_id and charges:
            # Fetch the technician details
            technician = frappe.get_doc("Technician Details", technician_id)  # Replace with actual DocType name if different
            
            # Ensure that the technician has a field for total amount or similar
            if hasattr(technician, 'total_amount_settled'):
                # Subtract charges from the technician's total amount
                technician.total_amount_settled -= charges  # Adjust the field name if necessary

                # Save the changes
                technician.save()

                # Log the action
                frappe.log_error(f"Technician Amount Updated: Technician ID {technician_id}, Charges Subtracted {charges}", "Technician Amount Update")

        # else:
        #     frappe.throw(("Technician ID or charges not found for the Technician Visit Entry."))


    def validate(self):
        update_technician_charge(self)






from frappe.utils import flt
import frappe

def update_technician_charge(doc):
    if not doc.technician_category or not doc.kilometers:
        return

    settings = frappe.get_single("Admin Settings")

    for row in settings.technician_charges_table:
        if (
            row.category == doc.technician_category
            and flt(row.from_distance) <= flt(doc.kilometers) <= flt(row.to_distance)
        ):

            # Type = Pickup
            if doc.type == "Pickup":
                doc.charges = row.pickup

            # Type = Delivery
            elif doc.type == "Delivery":
                doc.charges = row.delivery

            # Any other type defaults to Delivery charge
            else:
                doc.charges = row.delivery

            break