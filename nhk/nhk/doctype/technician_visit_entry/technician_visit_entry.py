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
