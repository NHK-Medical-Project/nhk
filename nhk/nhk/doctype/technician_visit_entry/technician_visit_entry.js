// Copyright (c) 2024, vishnu and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Technician Visit Entry", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Technician Visit Entry', {
    check_kilometers_and_proceed: function(frm, callback) {
        let fields = [];
        let has_kms = !!frm.doc.kilometers;
        let has_charges = frm.doc.charges && parseFloat(frm.doc.charges) > 0;

        if (!has_kms) {
            fields.push({
                fieldname: 'kilometers',
                fieldtype: 'Float',
                label: __('Kilometers'),
                description: __('If left empty, it will default to 1')
            });
        }

        if (!has_charges) {
            fields.push({
                fieldname: 'charges',
                fieldtype: 'Currency',
                label: __('Incentive Amount (Charges)'),
                default: 1.0,
                description: __('If left empty, it will default to 1')
            });
        }

        if (fields.length === 0) {
            callback();
        } else {
            frappe.prompt(fields, function(values) {
                if (!has_kms) {
                    let kms = values.kilometers;
                    if (kms === undefined || kms === null || kms === "" || parseFloat(kms) <= 0) {
                        kms = 1.0;
                    }
                    frm.set_value('kilometers', kms);
                }

                if (!has_charges) {
                    let val = values.charges;
                    if (val === undefined || val === null || val === "" || parseFloat(val) <= 0) {
                        val = 1.0;
                    }
                    frm.set_value('charges', val);
                }

                if (frm.is_dirty()) {
                    frm.save(null, function() {
                        callback();
                    });
                } else {
                    callback();
                }
            }, __('Required Information'), __('Submit'));
        }
    },
    check_incentive_amount_and_proceed: function(frm, callback) {
        let default_val = frm.doc.incentive_amount_to_be_processed || frm.doc.charges || 1.0;
        frappe.prompt([
            {
                fieldname: 'incentive_amount',
                fieldtype: 'Currency',
                label: __('Incentive Amount to be Processed'),
                default: default_val,
                description: __('If left empty, it will default to {0}', [default_val])
            }
        ], function(values) {
            let amt = values.incentive_amount;
            if (amt === undefined || amt === null || amt === "" || parseFloat(amt) <= 0) {
                amt = default_val;
            }
            frm.set_value('incentive_amount_to_be_processed', amt);
            frm.set_value('charges', amt);
            if (frm.is_dirty()) {
                frm.save(null, function() {
                    callback();
                });
            } else {
                callback();
            }
        }, __('Enter Incentive Amount'), __('Submit'));
    },
    prompt_incentive_finalize: function(frm, callback) {
        let fields = [];
        let need_kms = !frm.doc.kilometers;

        if (need_kms) {
            fields.push({
                fieldname: 'kilometers',
                fieldtype: 'Float',
                label: __('Kilometers'),
                description: __('If left empty, it will default to 1')
            });
        }

        let default_incentive = frm.doc.charges || frm.doc.incentive_amount_to_be_processed || 1.0;
        fields.push({
            fieldname: 'incentive_amount',
            fieldtype: 'Currency',
            label: __('Incentive Amount'),
            default: default_incentive,
            description: __('If left empty, it will default to {0}', [default_incentive])
        });

        frappe.prompt(fields, function(values) {
            if (need_kms) {
                let kms = values.kilometers;
                if (kms === undefined || kms === null || kms === "" || parseFloat(kms) <= 0) {
                    kms = 1.0;
                }
                frm.set_value('kilometers', kms);
            }

            let amt = values.incentive_amount;
            if (amt === undefined || amt === null || amt === "" || parseFloat(amt) <= 0) {
                amt = default_incentive;
            }
            frm.set_value('incentive_amount_to_be_processed', amt);
            frm.set_value('charges', amt);

            if (frm.is_dirty()) {
                frm.save(null, function() {
                    callback();
                });
            } else {
                callback();
            }
        }, __('Enter Incentive Details'), __('Submit'));
    },
    after_save(frm) {
        if (frm.doc.type === 'Service' && frm.doc.technician_user_id && frappe.user.has_role("NHK Admin")) {
            // Call the custom server-side method to update shares
            frappe.call({
                method: 'nhk.custom_script.update_shares',
                args: {
                    doctype: frm.doc.doctype,  // Document type
                    docname: frm.doc.name,     // Document name
                    technician_user_id: frm.doc.technician_user_id  // New technician_user_id
                },
                callback: function(response) {
                    if (response.message) {
                        frappe.show_alert(__('Document shared with read and write access to the technician.'));
                    } else {
                        frappe.msgprint(__('Failed to share the document.'));
                    }
                }
            });
        }
    },
    refresh(frm) {
        if (frm.doc.type === 'Service'){
            frm.set_df_property('sales_order_id', 'read_only', 0);
        }
        if (frm.doc.type === 'Delivery'|| frm.doc.type === 'Pickup'){
            frm.set_df_property('sales_order_id', 'read_only', 1);
        }
        if (frm.doc.status !== 'Assigned') {
            frm.set_df_property('technician_id', 'read_only', 1);
        }
        if (frm.doc.status === 'Closed') {
            frm.set_df_property('charges', 'read_only', 1);
            frm.set_df_property('kilometers', 'read_only', 1);
            frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
            frm.set_df_property('patient_id', 'read_only', 1);
            frm.set_df_property('area', 'read_only', 1);
            frm.set_df_property('notes', 'read_only', 1);
            frm.set_df_property('order', 'read_only', 1);
        }
if ((frm.doc.status === 'Incentive Finalize') && frappe.user.has_role("NHK Admin")) {
            frm.set_df_property('charges', 'read_only', 1);
            frm.set_df_property('kilometers', 'read_only', 1);
            frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
            
             // 1. Existing Revert Status Button
            frm.add_custom_button(__('Revert Status'), function() {
                let newStatus;
                if (frm.doc.type === 'Pickup') {
                    newStatus = 'Picked up';
                } else if (frm.doc.type === 'Delivery') {
                    newStatus = 'Delivered';
                } else {
                    frappe.msgprint(__('Invalid type for status reversion.'));
                    return;
                }

                frappe.confirm(
                    __('Are you sure you want to revert the status to {0}?', [newStatus]),
                    function() {
                        frm.set_value('status', newStatus);
                        frappe.show_alert(__('Status reverted to {0}.', [newStatus]));
                        frm.save();
                        setTimeout(() => {
                            window.location.reload();
                        }, 1000);

                    },
                    function() {
                        frappe.msgprint(__('Operation cancelled.'));
                    }
                );
            }, __('Action'));


            // 2. NEW OPTION: Payment Cleared & Close Status Button
            frm.add_custom_button(__('Payment Cleared & Close'), function() {
                frappe.confirm(
                    __('Are you sure you want to mark the payment as Cleared and Close this record?'),
                    function() {
                        // Set the exact fields requested
                        frm.set_value('payment_status', 'Cleared');
                        frm.set_value('status', 'Closed');
                        
                        frappe.show_alert({message: __('Payment Cleared and Record Closed.'), indicator: 'green'});
                        frm.save();
                        
                        setTimeout(() => {
                            window.location.reload();
                        }, 1000);
                    },
                    function() {
                        // On cancel, do nothing
                        frappe.msgprint(__('Operation cancelled.'));
                    }
                );
            }, __('Action'));

        }
        
        if (frm.doc.status === 'Amount Settled' && frappe.user.has_role("NHK Admin")) {
            frm.set_df_property('sales_order_id', 'read_only', 1);
            frm.set_df_property('charges', 'read_only', 1);
            frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
            frm.set_df_property('kilometers', 'read_only', 1);
            frm.add_custom_button(__('Close'), function() {
                // Check if kilometers and charges are filled
                
                    // Confirm before changing status
                    frappe.confirm(
                        `Are you sure you want to change the status to Close?`,
                        function() {
                            // Call the server-side method to change status
                            frappe.call({
                                method: "nhk.custom_script.change_status", // Update with your actual method path
                                args: {
                                    docname: frm.doc.name,
                                    new_status: 'Closed',
                                    charges: frm.doc.charges,
                                    incentive_amount: frm.doc.incentive_amount_to_be_processed
                                },
                                callback: function(response) {
                                    if (response.message) {
                                        // Show success message
                                        frappe.show_alert({ message: response.message, indicator: 'green' });
                                        setTimeout(() => {
                                            window.location.reload();
                                        }, 1000);
                                        // Refresh the form to reflect the changes
                                        frm.refresh();
                                    } else {
                                        frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
                                    }
                                },
                                error: function(error) {
                                    frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
                                }
                            });
                        },
                        function() {
                            // Handle cancel case
                            frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
                        }
                    );
                
            },('Action'));
        }

        if (frm.doc.status === 'Delivered' || frm.doc.status === 'Picked up'||frm.doc.status === 'Installation Done'|| frm.doc.status === 'Service Done')  {
            frm.set_df_property('sales_order_id', 'read_only', 1);
        }
        
        if ((frm.doc.status === 'Delivered' || frm.doc.status === 'Picked up'||frm.doc.status === 'Installation Done'|| frm.doc.status === 'Service Done') && frappe.user.has_role("NHK Admin")) {
            
            frm.add_custom_button(__('Incentive Finalize'), function() {
                frm.events.prompt_incentive_finalize(frm, function() {
                    // Show confirmation dialog
                    frappe.confirm(
                        __('Are you sure you want to mark this as Ready for Payment?') + 
                        '<br><br>' + 
                        __('Incentive Amount: ') + frm.doc.incentive_amount_to_be_processed + 
                        '<br>' + 
                        __('Kilometers: ') + frm.doc.kilometers,
                        function() {                            
                            frappe.call({
                                method: "nhk.custom_script.change_status", // Update with your actual method path
                                args: {
                                    docname: frm.doc.name,
                                    new_status: 'Incentive Finalize',
                                    charges: frm.doc.charges,
                                    incentive_amount: frm.doc.incentive_amount_to_be_processed
                                },
                                callback: function(response) {
                                    if (response.message) {
                                        // Show success message
                                        frappe.show_alert({ message: response.message, indicator: 'green' });
                                        setTimeout(() => {
                                            window.location.reload();
                                        }, 1000);
                                        // Refresh the form to reflect the changes
                                        frm.refresh();
                                    } else {
                                        frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
                                    }
                                },
                                error: function(error) {
                                    frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
                                }
                            });
                        },
                        function() {
                            // On cancel, do nothing
                            frappe.msgprint(__('Operation cancelled.'));
                        }
                    );
                });
            }, __('Action'));
        }

        
        // if (frm.doc.status === 'Assigned' && frm.doc.type === 'Pickup')  {
        //         frm.add_custom_button(__('Picked Up'), function() {
        //             frm.events.check_kilometers_and_proceed(frm, function() {
        //                 // Confirm before changing status
        //                 frappe.confirm(
        //                     `Are you sure you want to change the status to Pickup?`,
        //                     function() {
        //                         // Call the server-side method to change status
        //                         frappe.call({
        //                             method: "nhk.custom_script.change_status", // Update with your actual method path
        //                             args: {
        //                                 docname: frm.doc.name,
        //                                 new_status: 'Picked up'
        //                             },
        //                             callback: function(response) {
        //                                 if (response.message) {
        //                                     // Show success message
        //                                     frappe.show_alert({ message: response.message, indicator: 'green' });
        //                                                 setTimeout(() => {
        //                                                     window.location.reload();
        //                                                 }, 1000);
        //                                     // Refresh the form to reflect the changes
        //                                     frm.refresh();
        //                                 } else {
        //                                     frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
        //                                 }
        //                             },
        //                             error: function(error) {
        //                                 frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
        //                             }
        //                         });
        //                     },
        //                     function() {
        //                         // Handle cancel case
        //                         frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
        //                     }
        //                 );
        //             });
        //         },('Action'));
        //     }
                    // if (frm.doc.status === 'Assigned' && frm.doc.type === 'Technician Assignment For Sales')  {
                    //     frm.add_custom_button(__('Installation Done'), function() {
                    //         if (!frm.doc.kilometers || !frm.doc.charges) {
                    //             frappe.msgprint(__('Please enter Kilometers and Charges before changing the status to Delivered.'));
                    //             frappe.validated = false;
                    //             return; // Stop the process if validation fails
                    //         }
                    //         // Confirm before changing status
                    //         frappe.confirm(
                    //             `Are you sure you want to change the status to Installation Done?`,
                    //             function() {
                    //                 // Call the server-side method to change status
                    //                 frappe.call({
                    //                     method: "nhk.custom_script.change_status", // Update with your actual method path
                    //                     args: {
                    //                         docname: frm.doc.name,
                    //                         new_status: 'Installation Done'
                    //                     },
                    //                     callback: function(response) {
                    //                         if (response.message) {
                    //                             // Show success message
                    //                             frappe.show_alert({ message: response.message, indicator: 'green' });
                    //                                         setTimeout(() => {
                    //             						window.location.reload();
                    //             					}, 1000);
                    //                             // Refresh the form to reflect the changes
                    //                             frm.refresh();
                    //                         } else {
                    //                             frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
                    //                         }
                    //                     },
                    //                     error: function(error) {
                    //                         frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
                    //                     }
                    //                 });
                    //             },
                    //             function() {
                    //                 // Handle cancel case
                    //                 frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
                    //             }
                    //         );
                    //     },('Action'));
                    // }
                    //                     if (frm.doc.status === 'Assigned' && frm.doc.type === 'Technician Assignment For Service')  {
                    //     frm.add_custom_button(__('Service Done'), function() {
                    //         if (!frm.doc.kilometers || !frm.doc.charges) {
                    //             frappe.msgprint(__('Please enter Kilometers and Charges before changing the status to Delivered.'));
                    //             frappe.validated = false;
                    //             return; // Stop the process if validation fails
                    //         }
                    //         // Confirm before changing status
                    //         frappe.confirm(
                    //             `Are you sure you want to change the status to Installation Done?`,
                    //             function() {
                    //                 // Call the server-side method to change status
                    //                 frappe.call({
                    //                     method: "nhk.custom_script.change_status", // Update with your actual method path
                    //                     args: {
                    //                         docname: frm.doc.name,
                    //                         new_status: 'Service Done'
                    //                     },
                    //                     callback: function(response) {
                    //                         if (response.message) {
                    //                             // Show success message
                    //                             frappe.show_alert({ message: response.message, indicator: 'green' });
                    //                                         setTimeout(() => {
                    //             						window.location.reload();
                    //             					}, 1000);
                    //                             // Refresh the form to reflect the changes
                    //                             frm.refresh();
                    //                         } else {
                    //                             frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
                    //                         }
                    //                     },
                    //                     error: function(error) {
                    //                         frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
                    //                     }
                    //                 });
                    //             },
                    //             function() {
                    //                 // Handle cancel case
                    //                 frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
                    //             }
                    //         );
                    //     },('Action'));
                    // }








            // --- ACTION 1: Service Done Action ---
        if (frm.doc.status === 'Assigned' && frm.doc.type === 'Technician Assignment For Service') {
            frm.add_custom_button(__('Service Done'), function() {
                frm.events.check_kilometers_and_proceed(frm, function() {
                    frappe.confirm(
                        __('Are you sure you want to change the status to Service Done?'),
                        function() {
                            frm.events.call_change_status(frm, 'Service Done');
                        }
                    );
                });
            }, __('Action'));
        }

        // --- ACTION 2: Installation Done Action ---
        if (frm.doc.status === 'Assigned' && frm.doc.type === 'Technician Assignment For Sales') {
            frm.add_custom_button(__('Installation Done'), function() {
                frm.events.check_kilometers_and_proceed(frm, function() {
                    frappe.confirm(
                        __('Are you sure you want to change the status to Installation Done?'),
                        function() {
                            frm.events.call_change_status(frm, 'Installation Done');
                        }
                    );
                });
            }, __('Action'));
        }
            
            if (frm.doc.status === 'Assigned' && frm.doc.type === 'Service')  {
                frm.add_custom_button(__('Service Done'), function() {
                    frm.events.check_kilometers_and_proceed(frm, function() {
                        // Confirm before changing status
                        frappe.confirm(
                            `Are you sure you want to change the status to Service Done?`,
                            function() {
                                // Call the server-side method to change status
                                frappe.call({
                                    method: "nhk.custom_script.change_status_sales", // Update with your actual method path
                                    args: {
                                        docname: frm.doc.name,
                                        new_status: 'Service Done'
                                    },
                                    callback: function(response) {
                                        if (response.message) {
                                            // Show success message
                                            frappe.show_alert({ message: response.message, indicator: 'green' });
                                                        setTimeout(() => {
                                                            window.location.reload();
                                                        }, 1000);
                                            // Refresh the form to reflect the changes
                                            frm.refresh();
                                        } else {
                                            frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
                                        }
                                    },
                                    error: function(error) {
                                        frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
                                    }
                                });
                            },
                            function() {
                                // Handle cancel case
                                frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
                            }
                        );
                    });
                },('Action'));
            }
        // if (frm.doc.status === 'Assigned' && frm.doc.type === 'Delivery')  {
        //         frm.add_custom_button(__('Delivered'), function() {
        //             frm.events.check_kilometers_and_proceed(frm, function() {
        //                 // Confirm before changing status
        //                 frappe.confirm(
        //                     `Are you sure you want to change the status to Delivered?`,
        //                     function() {
        //                         // Call the server-side method to change status
        //                         frappe.call({
        //                             method: "nhk.custom_script.change_status", // Update with your actual method path
        //                             args: {
        //                                 docname: frm.doc.name,
        //                                 new_status: 'Delivered'
        //                             },
        //                             callback: function(response) {
        //                                 if (response.message) {
        //                                     // Show success message
        //                                     frappe.show_alert({ message: response.message, indicator: 'green' });
        //                                                 setTimeout(() => {
        //                     						window.location.reload();
        //                     					}, 1000);
        //                                     // Refresh the form to reflect the changes
        //                                     frm.refresh();
        //                                 } else {
        //                                     frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
        //                                 }
        //                             },
        //                             error: function(error) {
        //                                 frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
        //                             }
        //                         });
        //                     },
        //                     function() {
        //                         // Handle cancel case
        //                         frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
        //                     }
        //                 );
        //             });
        //         },('Action'));
        //     }
        // if (frm.doc.sales_order_id && (frm.doc.type === 'Delivery' || frm.doc.type === 'Pickup')) {
        if (frm.doc.sales_order_id ) {    
            // Call a custom server-side function to get Sales Order details
            frappe.call({
                method: "nhk.custom_script.get_sales_order_details",
                args: {
                    sales_order_id: frm.doc.sales_order_id
                },
                callback: function( r) {
                    // console.log(frm)
                    if (r.message) {
                        // Format the balance amount in INR
                        let formatted_rental_balance = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.balance_amount);
                        let formatted_security_deposit_balance = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.outstanding_security_deposit_amount);
                        
                        
                        let formatted_paid_rental = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.paid_rental_amount);
                        let formatted_unpaid_rental = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.unpaid_rental_amount);
                        let formatted_paid_security_deposit = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.paid_security_deposit_amount);
                        let formatted_unpaid_security_deposit = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.unpaid_security_deposit_amount);
                        const targetItemCode = frm.doc.item_code;
                        // Prepare the HTML with proper padding and margin using flexbox
                        let sales_order_html = `
                            <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; font-family: Arial, sans-serif;">
                            <h3 style="text-align: center; color: black;">Sales Order Details</h3>
                            <div style="display: flex; flex-wrap: wrap; padding: 10px;">
                                <!-- Column 1 -->
                                <div class="column" style="flex: 1 1 33.33%; padding: 10px; box-sizing: border-box;">
                                    <h4 style="color: #333;">Customer Information</h4>
                                    <p><strong>Name:</strong> ${r.message.customer}</p>
                                    <p><strong>Mobile:</strong> ${r.message.customer_mobile_no}</p>
                                    <p><strong>Email:</strong> ${r.message.customer_email_id}</p>
                                    <p><strong>Address:</strong> ${r.message.permanent_address}</p>
                                </div>
                        
                                <!-- Column 2 -->
                                <div class="column" style="flex: 1 1 33.33%; padding: 10px; box-sizing: border-box;">
                                    <h4 style="color: #333;">Payment & Status</h4>
                                    <p><strong>Rental Balance Amount:</strong> ${formatted_rental_balance}</p>
                                    <p><strong>Security Deposit Balance Amount:</strong> ${formatted_security_deposit_balance}</p>
                                    <p><strong>Payment Status:</strong> ${r.message.payment_status}</p>
                                    <p><strong>Security Deposit Status:</strong> ${r.message.security_deposit_status}</p>
                                    <p><strong>Sales Order Status:</strong> ${r.message.status}</p>
                                </div>
                        
                                <!-- Column 3: Buttons Section -->
                                <div class="column" style=" text-align: center; padding: 10px; box-sizing: border-box;">
                                    <h4 style="color: #333;">Actions</h4>
                                    ${ (r.message.status === "Ready for Delivery" && frm.doc.type == 'Delivery') ? `
                                        <button class="btn-dispatched" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                            DISPATCHED
                                        </button>` : '' }
                        
                                    ${ (r.message.status === "DISPATCHED" && frm.doc.type == 'Delivery') ? `
                                        <button class="btn-delivered" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                            DELIVERED
                                        </button>` : '' }
                        
                                    ${ (r.message.status === "Ready for Pickup" && frm.doc.type === 'Pickup') ? `
                                        <button class="btn-pickup" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                            Pick Up
                                        </button>` : '' }
                        
                                    ${ (r.message.status === "Picked Up" && frm.doc.type === 'Pickup') ? `
                                        <button class="btn-submit_to_office" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                            Submitted to Office
                                        </button>` : '' }
                                </div>
                            </div>
                        </div>
                        
                        <style>
                            @media (max-width: 768px) {
                                .column {
                                    flex: 1 1 100%;
                                    max-width: 100%;
                                }
                            }
                        </style>




                                <div>
                                    <h4 style="color: #333;">Items</h4>
                                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                                        <thead>
                                            <tr>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Item Code</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Item Name</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Status</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Action</th>
                                                

                                            </tr>
                                        </thead>
                                        <tbody>
                                        ${r.message.items.map(item => {
                                            // Check if the current item code matches the target item code and handle different statuses
                                            let isTargetItem = item.item_code === targetItemCode;
                                            let buttonHTML = '';
                                        
                                            if (isTargetItem && item.child_status === 'Ready for Pickup') {
                                                buttonHTML = `
                                                    <div class="btn-group">
                                                        <div class="dropdown">
                                                            <button class="btn btn-secondary btn-sm dropdown-toggle" type="button" id="dropdownMenuButton" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="background-color: #3498db; color: white;">
                                                                Actions
                                                            </button>
                                                            <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
                                                                <button class="dropdown-item picked-up-button" data-item-code="${item.item_code}" data-id="${item.name}" data-name="${item.item_name}">Picked Up</button>
                                                            </div>
                                                        </div>
                                                    </div>
                                                `;
                                            } else if (isTargetItem && item.child_status === 'Picked Up') {
                                                buttonHTML = `
                                                    <div class="btn-group">
                                                        <div class="dropdown">
                                                            <button class="btn btn-info btn-sm dropdown-toggle" type="button" id="dropdownMenuButton" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="z-index: 1; background-color: #3498db;">
                                                                Actions
                                                            </button>
                                                            <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
                                                                <button class="dropdown-item submitted-to-office-button" data-item-code="${item.item_code}" data-id="${item.name}" data-name="${item.item_name}">Submitted to Office</button>
                                                                
                                                            </div>
                                                        </div>
                                                    </div>
                                                `;
                                            }
                                        
                                            return `
                                                <tr style="background-color: ${isTargetItem ? '#e0f7fa' : 'transparent'};">
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${item.item_code}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${item.item_name}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${item.child_status}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">
                                                        ${buttonHTML ? buttonHTML : ''}
                                                    </td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                    </table>

                                </div>
                                

                                <!-- Payment and Journal Entries Table -->
                                 <!-- Check the payment status and show the button for creating payment entry if necessary -->
                                    ${(r.message.rental_payment_status === "Partially Paid" || 
                                           r.message.rental_payment_status === "Unpaid" || 
                                           r.message.security_deposit_payment_status === "Unpaid" || 
                                           r.message.security_deposit_payment_status === "Partially Paid") && 
                                           frm.doc.status == "Assigned" ? `
                                        <div style="text-align: right; ">
                                            <button class="btn-create-payment" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                                Create Payment Entry
                                            </button>
                                        </div>
                                    ` : ''}
                                <div>
                                    <h4 style="color: #333;">Payment and Journal Entries</h4>
                                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                                        <thead>
                                            <tr>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Type</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Entry ID</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Posting Date</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Amount</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Status</th>
                                                <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Action</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${r.message.payment_entries.map(entry => `
                                                <tr>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">Payment Entry</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">
                                                                    ${frappe.user.has_role("NHK Admin") ? `<a href="/app/payment-entry/${entry.name}" target="_blank">${entry.name}</a>` : `${entry.name}`}
                                                                </td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${entry.posting_date}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(entry.amount)}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${entry.status}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">
                                                        ${entry.status === "Draft" && frappe.user.has_role("NHK Admin") ? `
                                                            <button class="btn-submit" data-entry-name="${entry.name}" data-doctype="Payment Entry" style="padding: 5px 10px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                                                Submit
                                                            </button>
                                                        ` : ''}
                                                    </td>
                                                </tr>
                                            `).join('')}
                                            ${r.message.journal_entries.map(entry => `
                                                <tr>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">Journal Entry</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">
                                                                    ${frappe.user.has_role("NHK Admin") ? `<a href="/app/journal-entry/${entry.name}" target="_blank">${entry.name}</a>` : `${entry.name}`}
                                                                </td>                                                    <td style="border: 1px solid #ddd; padding: 8px;">${entry.posting_date}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(entry.amount)}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">${entry.status}</td>
                                                    <td style="border: 1px solid #ddd; padding: 8px;">
                                                        ${entry.status === "Draft" && frappe.user.has_role("NHK Admin") ? `
                                                            <button class="btn-submit" data-entry-name="${entry.name}" data-doctype="Journal Entry" style="padding: 5px 10px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                                                Submit
                                                            </button>
                                                        ` : ''}
                                                    </td>
                                                </tr>
                                            `).join('')}
                                        </tbody>



                                    </table>
                                    
                                </div>
                            </div>
                            
                            <!-- Paid and Unpaid Amounts for Rental and Security Deposit -->
                           <div style="display: flex; justify-content: space-between; margin-top: 20px; font-family: Arial, sans-serif; color: #202124; flex-wrap: wrap;">
                                    <div style="flex: 1; padding-right: 20px; min-width: 250px; box-sizing: border-box;">
                                        <h4 style="color: black; font-weight: 600; margin-bottom: 10px;">Rental Payment Status</h4>
                                        <p style="margin: 5px 0;"><strong>Paid Rental Amount:</strong> <span style="color: #3c4043;">${formatted_paid_rental}</span></p>
                                        <p style="margin: 5px 0;"><strong>Unpaid Rental Amount:</strong> <span style="color: #ea4335;">${formatted_unpaid_rental}</span></p>
                                        <p style="margin: 5px 0;"><strong>Rental Payment Status:</strong> <span style="color: #3c4043;">${r.message.rental_payment_status}</span></p>
                                    </div>
                                    <div style="flex: 1; min-width: 250px; box-sizing: border-box; ">
                                        <h4 style="color: black; font-weight: 600; margin-bottom: 10px;">Security Deposit Payment Status</h4>
                                        <p style="margin: 5px 0;"><strong>Paid Security Deposit Amount:</strong> <span style="color: #3c4043;">${formatted_paid_security_deposit}</span></p>
                                        <p style="margin: 5px 0;"><strong>Unpaid Security Deposit Amount:</strong> <span style="color: #ea4335;">${formatted_unpaid_security_deposit}</span></p>
                                        <p style="margin: 5px 0;"><strong>Security Deposit Payment Status:</strong> <span style="color: #3c4043;">${r.message.security_deposit_payment_status}</span></p>
                                    </div>
                                </div>

                            </div>
                            
                            `;
                
                        // Check the payment status and show the button for creating payment entry if necessary
                        // if (r.message.rental_payment_status === "Partially Paid" || r.message.rental_payment_status === "Unpaid" || r.message.security_deposit_payment_status === "Unpaid"  || r.message.security_deposit_payment_status === "Partially Paid") {
                        //     sales_order_html += `
                        //         <div style="text-align: center; margin-top: 20px;">
                        //             <button class="btn-create-payment" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        //                 Create Payment Entry
                        //             </button>
                        //         </div>`;
                        // }
                        
                        // Show dispatched button if status is 'Ready for Delivery'
                        // if (r.message.status === "Ready for Delivery" && frm.doc.type == 'Delivery') {
                        //     sales_order_html += `
                        //         <div style="text-align: center; margin-top: 20px;">
                        //             <button class="btn-dispatched" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        //                 DISPATCHED
                        //             </button>
                        //         </div>`;
                        // }
                        
                        // if (r.message.status === "DISPATCHED" && frm.doc.type == 'Delivery') {
                        //     sales_order_html += `
                        //         <div style="text-align: center; margin-top: 20px;">
                        //             <button class="btn-delivered" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        //                 DELIVERED
                        //             </button>
                        //         </div>`;
                        // }
                        
                        // if (r.message.status === "Ready for Pickup" && frm.doc.type === 'Pickup') {
                        //     sales_order_html += `
                        //         <div style="text-align: center; margin-top: 20px;">
                        //             <button class="btn-pickup" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        //                 Pick Up
                        //             </button>
                        //         </div>`;
                        // }
                        // if (r.message.status === "Picked Up" && frm.doc.type === 'Pickup') {
                        //     sales_order_html += `
                        //         <div style="text-align: center; margin-top: 20px;">
                        //             <button class="btn-submit_to_office" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        //                 Submitted to Ofice
                        //             </button>
                        //         </div>`;
                        // }

                        // Set the HTML content in the sales_order_html field
                        frm.fields_dict['sales_order_html'].html(sales_order_html);
                        
                        
                        // Add event listeners for dropdown and action buttons
                        // Add event listeners for action buttons
                        const pickedUpButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.picked-up-button');
                        const backToActiveButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.back-to-active-button');
                        
                        pickedUpButtons.forEach(button => {
                            button.addEventListener('click', () => {
                                const sales_order_id = frm.doc.sales_order_id
                                const itemCode = button.getAttribute('data-item-code');
                                const itemName = button.getAttribute('data-name');
                                const sales_order_item_id = button.getAttribute('data-id');
                                // console.log(itemCode, itemName,sales_order_id,sales_order_item_id)
                                updateStatusToPickedUp(itemCode,sales_order_id,sales_order_item_id); // Replace with your function to handle 'Picked Up'
                            });
                        });
                        
                        const submittedToofficeButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.submitted-to-office-button');

                        submittedToofficeButtons.forEach(button => {
                            button.addEventListener('click', () => {
                                const sales_order_id = frm.doc.sales_order_id
                                const itemCode = button.getAttribute('data-item-code');
                                const itemName = button.getAttribute('data-name');
                                const sales_order_item_id = button.getAttribute('data-id');
                                // console.log(itemCode, itemName,sales_order_id,sales_order_item_id)
                                promptForDateTimeForOfficeSubmission(itemCode, sales_order_id,sales_order_item_id);
                            });
                        });
                        
                        
                        // Add event listener for the Create Payment Entry button
                        const createPaymentButton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-create-payment');
                        if (createPaymentButton) {
                            createPaymentButton.addEventListener('click', () => {
                                create_payment_entry(r.message, frm.doc.sales_order_id,frm.doc.technician_id,frm.doc.name); // Pass the entire sales order details
                            });
                        }
                        
                            // Add event listener for the Dispatched button
                            const dispatchButton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-dispatched');
                            if (dispatchButton) {
                                dispatchButton.addEventListener('click', () => {
                                    change_sales_order_status_dispatched(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
                                });
                            }
                            
                            
                            const deliveredbutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-delivered');
                            if (deliveredbutton) {
                                deliveredbutton.addEventListener('click', () => {
                                    change_sales_order_status_delivered(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
                                });
                            }
                        
                        
                            const pickupbutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-pickup');
                            if (pickupbutton) {
                                pickupbutton.addEventListener('click', () => {
                                    console.log(r.message, frm.doc.sales_order_id)
                                    change_sales_order_status_pickup(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
                                });
                            }
                            
                            const submittiofficebutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-submit_to_office');
                            if (submittiofficebutton) {
                                submittiofficebutton.addEventListener('click', () => {
                                    console.log(r.message, frm.doc.sales_order_id)
                                    change_sales_order_status_submit_to_office(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
                                });
                            }
                        
                        frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.btn-submit').forEach(button => {
                            button.addEventListener('click', () => {
                                const entryName = button.getAttribute('data-entry-name');
                                const doctype = button.getAttribute('data-doctype');
                                submitEntry(entryName, doctype);  // Call the submit function with entry details
                            });
                        });
                    }
                }
            });
        }
    },
    call_change_status: function(frm, new_status) {
        frappe.call({
            method: "nhk.custom_script.change_status_sales", // Match your actual python path
            args: {
                docname: frm.doc.name,
                new_status: new_status
            },
            callback: function(response) {
                if (response.message) {
                    frappe.show_alert({ message: response.message, indicator: 'green' });
                    setTimeout(() => {
                        frm.reload_doc();
                    }, 1000);
                } else {
                    frappe.show_alert({ message: __('Error changing status.'), indicator: 'red' });
                }
            },
            error: function(error) {
                frappe.show_alert({ message: __('Error changing status: ') + error.message, indicator: 'red' });
            }
        });
    }
});

// Function to prompt for datetime and execute method for submission to office
function promptForDateTimeForOfficeSubmission(itemCode, sales_order_id,sales_order_item_id) {
    frappe.confirm(
        'Are you sure you want to mark this item as Submitted to Office?', // Confirmation message
        function() {
            frappe.prompt([
                {
                    fieldname: 'submission_datetime',
                    fieldtype: 'Datetime',
                    label: 'Submission Datetime',
                    default:'Now',
                    reqd: 1
                },
                {
        			label: 'Send Email',
        			fieldname: 'send_email',
        			fieldtype: 'Check',
        			default: 0,
        // 			read_only:1,
                    hidden:1,
        		},
        		{
        			label: 'Email ID',
        			fieldname: 'customer_email',
        			fieldtype: 'Data',
        // 			default: frm.doc.customer_email_id,
        			depends_on: 'eval:doc.send_email'
        		}
                
            ], function(values) {
                var submissionDatetime = values.submission_datetime;
                var send_email = values.send_email;
                var customer_email = values.customer_email;
                // console.log("Submission Datetime:", submissionDatetime, itemCode1,docname,name);
                // Call a function to execute method for submission to office
                updateStatusToSubmittedToOffice(itemCode, submissionDatetime,sales_order_id,sales_order_item_id,send_email,customer_email);
            }, 'Enter Submission Datetime', 'Submit');
        },
        function() {
            // If user cancels, do nothing
        }
    );
}


// Function to update status to Submitted to Office
function updateStatusToSubmittedToOffice(itemCode, submissionDatetime,sales_order_id,sales_order_item_id) {
    frappe.call({
        method: 'erpnext.selling.doctype.sales_order.sales_order.update_status_to_submitted_to_office',
        args: {
            item_code: itemCode,
            submission_datetime: submissionDatetime,
            send_email:send_email,
            customer_email:customer_email,
            docname: sales_order_id,
            child_name:sales_order_item_id
        },
        callback: function(response) {
            if (response.message) {
                // Success message
                frappe.msgprint("Item status updated to Submitted to Office successfully.");
                setTimeout(() => {
                    window.location.reload();
                }, 3000); // 3000 milliseconds = 1 second
            } else {
                // Error message
                frappe.msgprint("Failed to update item status to Submitted to Office.");
            }
        }
    });
}

function updateStatusToPickedUp(itemCode,sales_order_id,sales_order_item_id) {
    
    frappe.confirm(
        'Are you sure you want to mark this item as Picked Up?', // Confirmation message
        function() {
            frappe.prompt([
                {
                    fieldname: 'picked_up_datetime',
                    fieldtype: 'Datetime',
                    label: 'Picked Up Datetime',
                    default:'Now',
                    reqd: 1
                }
            //   {
            //         fieldname: 'technician_name',
            //         fieldtype: 'Link',
            //         options: 'Technician Details',
            //         label: 'Technician Name',
            //         reqd: 1,
            //         onchange: function() {
            //             // Function to dynamically update technician mobile based on selected technician
            //             var technicianName = this.value;
            //             if (technicianName) {
            //                 frappe.call({
            //                     method: 'frappe.client.get_value',
            //                     args: {
            //                         doctype: 'Technician Details',
            //                         filters: { 'name': technicianName },
            //                         fieldname: ['mobile_number']
            //                     },
            //                     callback: function(response) {
            //                         if (response.message && response.message.mobile_number) {
            //                             // Set the value of technician mobile
            //                             cur_dialog.fields_dict.technician_mobile.set_input(response.message.mobile_number);
            //                         }
            //                     }
            //                 });
            //             }
            //         }
            //     },
            //     {
            //         fieldname: 'technician_mobile',
            //         fieldtype: 'Data',
            //         label: 'Technician Mobile Number',
            //         // reqd: 1
            //     }



            ], function(values) {
                var picked_up_datetime = values.picked_up_datetime;
                // var technicianMobile = values.technician_mobile;
                
                // Call a function to update status to Picked Up
                frappe.call({
                    method: 'erpnext.selling.doctype.sales_order.sales_order.update_status_to_picked_up',
                    args: {
                        item_code: itemCode,
                        docname: sales_order_id,
                        child_name: sales_order_item_id,
                        picked_up_datetime: picked_up_datetime
                    },
                    callback: function(response) {
                        if (response.message) {
                            // Success message
                            frappe.msgprint("Item picked up successfully.");
                            setTimeout(() => {
                                window.location.reload();
                            }, 3000); // 3000 milliseconds = 1 second
                        } else {
                            // Error message
                            frappe.msgprint("Failed to update item status.");
                        }
                    }
                });
            }, 'Enter Technician Details', 'Submit');
        },
        function() {
            // If user cancels, do nothing
        }
    );
}



function submitEntry(entryName, doctype) {
    frappe.confirm(
        `Are you sure you want to submit the ${doctype} entry: ${entryName}?`,
        function() {
            // If the user confirms, submit the entry
            frappe.call({
                method: "nhk.custom_script.submit_entry", // Update with your actual app and method path
                args: {
                    entry_name: entryName,
                    doctype: doctype
                },
                callback: function(response) {
                    if (response.message) {
                        frappe.show_alert({ 
                            message: response.message.message,  // Correctly accessing the message property
                            indicator: 'green' 
                        });
                        setTimeout(() => {
        						window.location.reload();
        					}, 1000);
                        // Optionally, refresh the page or update the table to reflect the changes
                        // location.reload(); // Uncomment to refresh the page
                    } else {
                        frappe.show_alert({ message: 'Error submitting entry.', indicator: 'red' });
                    }
                },
                error: function(error) {
                    frappe.show_alert({ message: 'Error submitting entry: ' + error.message, indicator: 'red' });
                }
            });
        },
        function() {
            // If the user cancels, show a cancel alert
            frappe.show_alert({ message: 'Submission canceled.', indicator: 'orange' });
        }
    );
}



function change_sales_order_status_submit_to_office(salesOrderDetails, salesOrderId) {
    console.log(salesOrderDetails, salesOrderId);
    
    // Check if items exist and is an array before mapping
    let itemCodes = Array.isArray(salesOrderDetails.items) ? salesOrderDetails.items.map(item => item.item_code) : [];
    console.log(itemCodes);
    
    // Prompt for the submitted date
    frappe.prompt([
        {
            label: 'Submitted Date',
            fieldname: 'submitted_date',
            fieldtype: 'Datetime',
            default: frappe.datetime.now_datetime(),
            reqd: 1
        },
        {
			label: 'Send Email',
			fieldname: 'send_email',
			fieldtype: 'Check',
			default: 0,
// 			read_only:1,
			hidden:1
		},
		{
			label: 'Email ID',
			fieldname: 'customer_email',
			fieldtype: 'Data',
// 			default: this.frm.doc.customer_email_id,
			depends_on: 'eval:doc.send_email'
		}
    ], (values) => {
        // Call the server method to update Sales Order with the entered values
        frappe.call({
            method: "erpnext.selling.doctype.sales_order.sales_order.make_submitted_to_office",
            args: {
                docname: salesOrderId,
                item_code: itemCodes,
                submitted_date: values.submitted_date,
                send_email:values.send_email,
                customer_email:values.customer_email,
                
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint("Sales Order status has been updated to Submitted to Office!");
                    setTimeout(() => {
                        window.location.reload();
                    }, 1000);
                } else {
                    frappe.msgprint("Error: " + response.message);
                }
            }
        });
    }, __('Submitted to Office'));
}





function change_sales_order_status_pickup(salesOrderDetails, salesOrderId) {
    // Prompt for the delivered date and other necessary details
    frappe.prompt([
        
        {
				label: 'Pick Up Date and Time',
				fieldname: 'pickup_date',
				fieldtype: 'Datetime',
                default: frappe.datetime.now_datetime(),
				reqd: 1
			}
    ], (values) => {
        // Update Sales Order with the entered values
        frappe.call({
            method: "erpnext.selling.doctype.sales_order.sales_order.make_pickedup", // Update this to your server method
            args: {
                docname: salesOrderId,
                pickup_date: values.pickup_date
                
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint("Sales Order status has been updated to Pick Up!");
                    setTimeout(() => {
        						window.location.reload();
        					}, 1000);
                   
                } else {
                    frappe.msgprint("Error: " + response.message);
                }
            }
        });
    }, __('Picked Up'));
}

function change_sales_order_status_delivered(salesOrderDetails, salesOrderId) {
    // Prompt for the delivered date and other necessary details
    frappe.prompt([
        {
            label: 'Delivered Date',
            fieldname: 'delivered_date',
            fieldtype: 'Datetime',
            default: frappe.datetime.now_datetime(), // Default to today's date
            reqd: 1
        },
        {
            fieldtype: 'Section Break'
        },
        {
            label: 'Payment Status',
            fieldname: 'payment_status',
            fieldtype: 'Data',
            default: salesOrderDetails.payment_status,
            read_only: 1
        },
        {
            label: 'Balance Amount',
            fieldname: 'balance_amount',
            fieldtype: 'Currency',
            default: salesOrderDetails.balance_amount,
            read_only: 1
        },
        {
            label: 'Payment Received Amount',
            fieldname: 'received_amount',
            fieldtype: 'Currency',
            default: salesOrderDetails.received_amount,
            read_only: 1
        },
        {
            fieldtype: 'Column Break'
        },
        {
            label: 'Security Deposit Payment Status',
            fieldname: 'security_deposit_payment_status',
            fieldtype: 'Data',
            default: salesOrderDetails.security_deposit_status,
            read_only: 1
        },
        {
            label: 'Payment Outstanding Security Deposit Amount',
            fieldname: 'outstanding_security_deposit_amount',
            fieldtype: 'Currency',
            default: salesOrderDetails.outstanding_security_deposit_amount,
            read_only: 1
        },
        {
            label: 'Received Security Deposit Amount',
            fieldname: 'paid_security_deposite_amount',
            fieldtype: 'Currency',
            default: salesOrderDetails.paid_security_deposite_amount,
            read_only: 1
        },
        {
            fieldtype: 'Section Break'
        },
        {
            label: 'Payment Pending Reason',
            fieldname: 'payment_pending_reason',
            fieldtype: 'Link',
            options: 'Payment Pending Reason',
            depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")',
            mandatory_depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")'
        },
        {
            label: 'Notes',
            fieldname: 'notes',
            fieldtype: 'Small Text',
            depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")',
        },
        {
            label: 'Rental Order Agreement Attachment',
            fieldname: 'rental_order_agreement_attachment',
            fieldtype: 'Attach',
        },
        {
            label: 'Aadhar Card Attachment',
            fieldname: 'aadhar_card_attachment',
            fieldtype: 'Attach',
        }
    ], (values) => {
        // Update Sales Order with the entered values
        frappe.call({
            method: "erpnext.selling.doctype.sales_order.sales_order.make_delivered", // Update this to your server method
            args: {
                docname: salesOrderId,
                customer_name:salesOrderDetails.customer,
                delivered_date: values.delivered_date,
                payment_pending_reason: values.payment_pending_reason,
                rental_order_agreement_attachment: values.rental_order_agreement_attachment,
            	aadhar_card_attachment: values.aadhar_card_attachment,
                notes: values.notes,
                
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint("Sales Order status has been updated to DELIVERED!");
                    setTimeout(() => {
        						window.location.reload();
        					}, 1000);
                   
                } else {
                    frappe.msgprint("Error: " + response.message);
                }
            }
        });
    }, __('DELIVERED'));
}




function change_sales_order_status_dispatched(salesOrderDetails, salesOrderId) {
    frappe.confirm(
        'Are you sure you want to change the status of this order to DISPATCHED?',
        () => {
            // Prompt for the dispatch date
            frappe.prompt([
                {
                    fieldname: 'dispatch_date',
                    fieldtype: 'Date',
                    label: 'Dispatch Date',
                    reqd: 1,
                    default: frappe.datetime.nowdate() // Set default to today's date
                }
            ],
            function(values) {
                // Call server method to update the sales order status with dispatch date
                frappe.call({
                    method: "erpnext.selling.doctype.sales_order.sales_order.make_dispatch",
                    args: {
                        docname: salesOrderId,
                        // new_status: "DISPATCHED",
                        dispatch_date: values.dispatch_date // Include dispatch date in the args
                    },
                    callback: function(response) {
                        if (response.message) {
                            frappe.msgprint("Sales Order status has been updated to DISPATCHED with dispatch date: " + values.dispatch_date);
                            // Optionally refresh the form to reflect the updated status
                            setTimeout(() => {
        						window.location.reload();
        					}, 1000);
                            
                        } else {
                            frappe.msgprint("Error: " + response.message);
                        }
                    }
                });
            },
            'Enter Dispatch Date', // Title for the prompt
            'Dispatch' // Button label for the prompt
            );
        }
    );
}



// JavaScript function to handle the payment entry creation
function create_payment_entry(sales_order_details, sales_order_id,technician_id,technician_visit_id) {
    // Open prompt to get customer payment details
    frappe.prompt([ {
            fieldname: 'customer_name',
            fieldtype: 'Link',
            options: 'Customer',
            label: 'Customer Name',
            read_only: 1,
            default: sales_order_details.customer
        },
        {
            fieldname: 'rental_payment_amount',
            fieldtype: 'Currency',
            label: 'Rental Payment Balance Amount',
            default: sales_order_details.unpaid_rental_amount
        },
        {
            fieldname: 'security_deposit_payment_amount',
            fieldtype: 'Currency',
            label: 'Security Deposit Balance Amount',
            default: sales_order_details.unpaid_security_deposit_amount
        },
        {
            fieldname: 'reference_no',
            fieldtype: 'Data',
            label: 'Cheque/Reference No',
            depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"',
            mandatory_depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"'
        },
        {
            fieldtype: 'Column Break'
        },
        {
            fieldname: 'payment_date',
            fieldtype: 'Date',
            label: 'Payment Date',
            default: 'Today',
            reqd: 1
        },
        {
            fieldname: 'mode_of_payment',
            fieldtype: 'Link',
            options: 'Mode of Payment',
            label: 'Mode Of Payment',
            mandatory_depends_on: 'eval:doc.rental_payment_amount || doc.security_deposit_payment_amount',
            reqd: 1,
            onchange: function() {
                var selectedModeOfPayment = this.value;
                if (selectedModeOfPayment) {
                    frappe.call({
                        method: 'erpnext.selling.doctype.sales_order.sales_order.get_default_account',
                        args: {
                            mode_of_payment: selectedModeOfPayment
                        },
                        callback: function(response) {
                            if (response.message) {
                                if (cur_dialog.fields_dict.rental_payment_amount.get_value() > 0) {
                                    cur_dialog.fields_dict.payment_account.set_input(response.message.default_account);
                                }
                                if (cur_dialog.fields_dict.security_deposit_payment_amount.get_value() > 0) {
                                    cur_dialog.fields_dict.security_deposit_account.set_input(response.message.journal_entry_default_account);
                                }
                            }
                        }
                    });
                }
            }
        },
        {
            fieldname: 'payment_account',
            fieldtype: 'Data',
            label: 'Payment Account',
            depends_on: 'eval:doc.rental_payment_amount',
            read_only: 1
        },
        {
            fieldname: 'security_deposit_account',
            fieldtype: 'Data',
            label: 'Security Deposit Account',
            depends_on: 'eval:doc.security_deposit_payment_amount',
            read_only: 1
        },
        {
            fieldname: 'reference_date',
            fieldtype: 'Date',
            label: 'Cheque/Reference Date',
            depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"',
            mandatory_depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"'
        },
        {
            fieldtype: 'Section Break'
        },
        {
            fieldname: 'remark',
            fieldtype: 'Small Text',
            label: 'Remark',
            description: 'Enter your remark here',
            placeholder: 'Remark',
            reqd: false
        }], function(values) {
        // Call process_payment with all the collected parameters
        frappe.call({
            method: 'erpnext.selling.doctype.sales_order.sales_order.process_payment',
            args: {
                balance_amount: sales_order_details.balance_amount,
                outstanding_security_deposit_amount: sales_order_details.outstanding_security_deposit_amount,
                customer_name: values.customer_name,
                rental_payment_amount: values.rental_payment_amount,
                sales_order_name: sales_order_id,                // Sales Order ID
                master_order_id: sales_order_details.master_order_id, // Master Order ID from sales order details
                security_deposit_status: sales_order_details.security_deposit_status, // Security Deposit Status
                customer: sales_order_details.customer,           // Customer Name
                payment_account: values.payment_account,          // Payment Account from prompt (if added)
                security_deposit_account: values.security_deposit_account, // Security Deposit Account (if added)
                reference_no: values.reference_no,
                reference_date: values.reference_date,
                mode_of_payment: values.mode_of_payment,
                payment_date: values.payment_date,
                security_deposit_payment_amount: values.security_deposit_payment_amount,
                remark: values.remark,
                from_technician_portal:1,
                technician_id:technician_id,
                technician_visit_id:technician_visit_id
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint("Payment processed successfully!");
                    setTimeout(() => {
						window.location.reload();
					}, 1000);
                } else {
                    frappe.msgprint("Error processing payment: " + response.message);
                }
            }
        });
    }, 'Enter Payment Details', 'Make Payment');
}







// frappe.ui.form.on('Technician Visit Entry', {
//  after_save(frm) {
//         if (frm.doc.type === 'Service' && frm.doc.technician_user_id) {
//             // Call the custom server-side method to update shares
//             frappe.call({
//                 method: 'nhk.custom_script.update_shares',
//                 args: {
//                     doctype: frm.doc.doctype,  // Document type
//                     docname: frm.doc.name,     // Document name
//                     technician_user_id: frm.doc.technician_user_id  // New technician_user_id
//                 },
//                 callback: function(response) {
//                     if (response.message) {
//                         frappe.show_alert(__('Document shared with read and write access to the technician.'));
//                     } else {
//                         frappe.msgprint(__('Failed to share the document.'));
//                     }
//                 }
//             });
//         }
//     },
//     refresh(frm) {
//         if (frm.doc.status !== 'Assigned') {
//             frm.set_df_property('technician_id', 'read_only', 1);
//         }
//         if (frm.doc.status === 'Closed') {
//             frm.set_df_property('charges', 'read_only', 1);
//             frm.set_df_property('kilometers', 'read_only', 1);
//             frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
//             frm.set_df_property('patient_id', 'read_only', 1);
//             frm.set_df_property('area', 'read_only', 1);
//             frm.set_df_property('notes', 'read_only', 1);
//             frm.set_df_property('order', 'read_only', 1);
//         }
//         if ((frm.doc.status === 'Incentive Finalize') && frappe.user.has_role("NHK Admin")) {
//             frm.set_df_property('charges', 'read_only', 1);
//             frm.set_df_property('kilometers', 'read_only', 1);
//             frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
            
            
//              // Add button to revert status based on type
//             frm.add_custom_button(__('Revert Status'), function() {
//                 // Check the type and set the status accordingly
//                 let newStatus;
//                 if (frm.doc.type === 'Pickup') {
//                     newStatus = 'Picked up';
//                 } else if (frm.doc.type === 'Delivery') {
//                     newStatus = 'Delivered';
//                 } else {
//                     frappe.msgprint(__('Invalid type for status reversion.'));
//                     return;
//                 }

//                 // Show confirmation before changing the status
//                 frappe.confirm(
//                     __('Are you sure you want to revert the status to {0}?', [newStatus]),
//                     function() {
//                         // Set the new status and save the form
//                         frm.set_value('status', newStatus);
//                           // Save the form
//                         frappe.show_alert(__('Status reverted to {0}.', [newStatus]));
//                         frm.save();
//                         setTimeout(() => {
//                             window.location.reload();
//                         }, 1000);

//                     },
//                     function() {
//                         // On cancel, do nothing
//                         frappe.msgprint(__('Operation cancelled.'));
//                     }
//                 );
//             }, __('Action'));

//         }

        
//         if (frm.doc.status === 'Amount Settled' && frappe.user.has_role("NHK Admin")) {
//             frm.set_df_property('charges', 'read_only', 1);
//             frm.set_df_property('incentive_amount_to_be_processed', 'read_only', 1);
//             frm.set_df_property('kilometers', 'read_only', 1);
//             frm.add_custom_button(__('Close'), function() {
//                 // Check if kilometers and charges are filled
                
//                     // Confirm before changing status
//                     frappe.confirm(
//                         `Are you sure you want to change the status to Close?`,
//                         function() {
//                             // Call the server-side method to change status
//                             frappe.call({
//                                 method: "nhk.custom_script.change_status", // Update with your actual method path
//                                 args: {
//                                     docname: frm.doc.name,
//                                     new_status: 'Closed'
//                                 },
//                                 callback: function(response) {
//                                     if (response.message) {
//                                         // Show success message
//                                         frappe.show_alert({ message: response.message, indicator: 'green' });
//                                         setTimeout(() => {
//                                             window.location.reload();
//                                         }, 1000);
//                                         // Refresh the form to reflect the changes
//                                         frm.refresh();
//                                     } else {
//                                         frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
//                                     }
//                                 },
//                                 error: function(error) {
//                                     frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
//                                 }
//                             });
//                         },
//                         function() {
//                             // Handle cancel case
//                             frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
//                         }
//                     );
                
//             },('Action'));
//         }

        
        
        
//         if ((frm.doc.status === 'Delivered' || frm.doc.status === 'Picked up'|| frm.doc.status === 'Service Done') && frappe.user.has_role("NHK Admin")) {
//             frm.add_custom_button(__('Incentive Finalize'), function() {
//                 // Check if kilometers and charges are filled
//                 if (frm.doc.kilometers && frm.doc.charges && frm.doc.incentive_amount_to_be_processed) {
//                     // Show confirmation dialog
//                     frappe.confirm(
//                         __('Are you sure you want to mark this as Ready for Payment?') + 
//                         '<br><br>' + 
//                         __('Incentive Amount: ') + frm.doc.incentive_amount_to_be_processed + 
//                         '<br>' + 
//                         __('Kilometers: ') + frm.doc.kilometers,
//                         function() {                            
//                             frappe.call({
//                                 method: "nhk.custom_script.change_status", // Update with your actual method path
//                                 args: {
//                                     docname: frm.doc.name,
//                                     new_status: 'Incentive Finalize'
//                                 },
//                                 callback: function(response) {
//                                     if (response.message) {
//                                         // Show success message
//                                         frappe.show_alert({ message: response.message, indicator: 'green' });
//                                         setTimeout(() => {
//                                             window.location.reload();
//                                         }, 1000);
//                                         // Refresh the form to reflect the changes
//                                         frm.refresh();
//                                     } else {
//                                         frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
//                                     }
//                                 },
//                                 error: function(error) {
//                                     frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
//                                 }
//                             });
// },
//                         function() {
//                             // On cancel, do nothing
//                             frappe.msgprint(__('Operation cancelled.'));
//                         }
//                     );
//                 } else {
//                     frappe.throw({ message: 'Please fill in kilometers and charges before settling the amount.', indicator: 'orange' });
//                 }
//             }, __('Action'));
//         }

        
        
//         if (frm.doc.status === 'Assigned' && frm.doc.type === 'Pickup')  {
//                 frm.add_custom_button(__('Picked Up'), function() {
//                     // Confirm before changing status
//                     frappe.confirm(
//                         `Are you sure you want to change the status to Pickup?`,
//                         function() {
//                             // Call the server-side method to change status
//                             frappe.call({
//                                 method: "nhk.custom_script.change_status", // Update with your actual method path
//                                 args: {
//                                     docname: frm.doc.name,
//                                     new_status: 'Picked up'
//                                 },
//                                 callback: function(response) {
//                                     if (response.message) {
//                                         // Show success message
//                                         frappe.show_alert({ message: response.message, indicator: 'green' });
//                                                     setTimeout(() => {
//                         						window.location.reload();
//                         					}, 1000);
//                                         // Refresh the form to reflect the changes
//                                         frm.refresh();
//                                     } else {
//                                         frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
//                                     }
//                                 },
//                                 error: function(error) {
//                                     frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
//                                 }
//                             });
//                         },
//                         function() {
//                             // Handle cancel case
//                             frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
//                         }
//                     );
//                 },('Action'));
//             }
            
//             if (frm.doc.status === 'Assigned' && frm.doc.type === 'Service')  {
//                 frm.add_custom_button(__('Service Done'), function() {
//                     // Confirm before changing status
//                     frappe.confirm(
//                         `Are you sure you want to change the status to Service Done?`,
//                         function() {
//                             // Call the server-side method to change status
//                             frappe.call({
//                                 method: "nhk.custom_script.change_status", // Update with your actual method path
//                                 args: {
//                                     docname: frm.doc.name,
//                                     new_status: 'Service Done'
//                                 },
//                                 callback: function(response) {
//                                     if (response.message) {
//                                         // Show success message
//                                         frappe.show_alert({ message: response.message, indicator: 'green' });
//                                                     setTimeout(() => {
//                         						window.location.reload();
//                         					}, 1000);
//                                         // Refresh the form to reflect the changes
//                                         frm.refresh();
//                                     } else {
//                                         frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
//                                     }
//                                 },
//                                 error: function(error) {
//                                     frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
//                                 }
//                             });
//                         },
//                         function() {
//                             // Handle cancel case
//                             frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
//                         }
//                     );
//                 },('Action'));
//             }
//         if (frm.doc.status === 'Assigned' && frm.doc.type === 'Delivery')  {
//                 frm.add_custom_button(__('Delivered'), function() {
//                     // Confirm before changing status
//                     frappe.confirm(
//                         `Are you sure you want to change the status to Delivered?`,
//                         function() {
//                             // Call the server-side method to change status
//                             frappe.call({
//                                 method: "nhk.custom_script.change_status", // Update with your actual method path
//                                 args: {
//                                     docname: frm.doc.name,
//                                     new_status: 'Delivered'
//                                 },
//                                 callback: function(response) {
//                                     if (response.message) {
//                                         // Show success message
//                                         frappe.show_alert({ message: response.message, indicator: 'green' });
//                                                     setTimeout(() => {
//                         						window.location.reload();
//                         					}, 1000);
//                                         // Refresh the form to reflect the changes
//                                         frm.refresh();
//                                     } else {
//                                         frappe.show_alert({ message: 'Error changing status.', indicator: 'red' });
//                                     }
//                                 },
//                                 error: function(error) {
//                                     frappe.show_alert({ message: 'Error changing status: ' + error.message, indicator: 'red' });
//                                 }
//                             });
//                         },
//                         function() {
//                             // Handle cancel case
//                             frappe.show_alert({ message: 'Status change canceled.', indicator: 'orange' });
//                         }
//                     );
//                 },('Action'));
//             }
//         if (frm.doc.sales_order_id && (frm.doc.type === 'Delivery' || frm.doc.type === 'Pickup')) {
            
//             // Call a custom server-side function to get Sales Order details
//             frappe.call({
//                 method: "nhk.custom_script.get_sales_order_details",
//                 args: {
//                     sales_order_id: frm.doc.sales_order_id
//                 },
//                 callback: function( r) {
//                     // console.log(frm)
//                     if (r.message) {
//                         // Format the balance amount in INR
//                         let formatted_rental_balance = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.balance_amount);
//                         let formatted_security_deposit_balance = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.outstanding_security_deposit_amount);
                        
                        
//                         let formatted_paid_rental = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.paid_rental_amount);
//                         let formatted_unpaid_rental = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.unpaid_rental_amount);
//                         let formatted_paid_security_deposit = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.paid_security_deposit_amount);
//                         let formatted_unpaid_security_deposit = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(r.message.unpaid_security_deposit_amount);
//                         const targetItemCode = frm.doc.item_code;
//                         // Prepare the HTML with proper padding and margin using flexbox
//                         let sales_order_html = `
//                             <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; font-family: Arial, sans-serif;">
//                             <h3 style="text-align: center; color: black;">Sales Order Details</h3>
//                             <div style="display: flex; flex-wrap: wrap; padding: 10px;">
//                                 <!-- Column 1 -->
//                                 <div class="column" style="flex: 1 1 33.33%; padding: 10px; box-sizing: border-box;">
//                                     <h4 style="color: #333;">Customer Information</h4>
//                                     <p><strong>Name:</strong> ${r.message.customer}</p>
//                                     <p><strong>Mobile:</strong> ${r.message.customer_mobile_no}</p>
//                                     <p><strong>Email:</strong> ${r.message.customer_email_id}</p>
//                                     <p><strong>Address:</strong> ${r.message.permanent_address}</p>
//                                 </div>
                        
//                                 <!-- Column 2 -->
//                                 <div class="column" style="flex: 1 1 33.33%; padding: 10px; box-sizing: border-box;">
//                                     <h4 style="color: #333;">Payment & Status</h4>
//                                     <p><strong>Rental Balance Amount:</strong> ${formatted_rental_balance}</p>
//                                     <p><strong>Security Deposit Balance Amount:</strong> ${formatted_security_deposit_balance}</p>
//                                     <p><strong>Payment Status:</strong> ${r.message.payment_status}</p>
//                                     <p><strong>Security Deposit Status:</strong> ${r.message.security_deposit_status}</p>
//                                     <p><strong>Sales Order Status:</strong> ${r.message.status}</p>
//                                 </div>
                        
//                                 <!-- Column 3: Buttons Section -->
//                                 <div class="column" style=" text-align: center; padding: 10px; box-sizing: border-box;">
//                                     <h4 style="color: #333;">Actions</h4>
//                                     ${ (r.message.status === "Ready for Delivery" && frm.doc.type == 'Delivery') ? `
//                                         <button class="btn-dispatched" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                             DISPATCHED
//                                         </button>` : '' }
                        
//                                     ${ (r.message.status === "DISPATCHED" && frm.doc.type == 'Delivery') ? `
//                                         <button class="btn-delivered" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                             DELIVERED
//                                         </button>` : '' }
                        
//                                     ${ (r.message.status === "Ready for Pickup" && frm.doc.type === 'Pickup') ? `
//                                         <button class="btn-pickup" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                             Pick Up
//                                         </button>` : '' }
                        
//                                     ${ (r.message.status === "Picked Up" && frm.doc.type === 'Pickup') ? `
//                                         <button class="btn-submit_to_office" style="padding: 10px 20px; background-color: #FF9800; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                             Submitted to Office
//                                         </button>` : '' }
//                                 </div>
//                             </div>
//                         </div>
                        
//                         <style>
//                             @media (max-width: 768px) {
//                                 .column {
//                                     flex: 1 1 100%;
//                                     max-width: 100%;
//                                 }
//                             }
//                         </style>




//                                 <div>
//                                     <h4 style="color: #333;">Items</h4>
//                                     <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
//                                         <thead>
//                                             <tr>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Item Code</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Item Name</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Status</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Action</th>
                                                

//                                             </tr>
//                                         </thead>
//                                         <tbody>
//                                         ${r.message.items.map(item => {
//                                             // Check if the current item code matches the target item code and handle different statuses
//                                             let isTargetItem = item.item_code === targetItemCode;
//                                             let buttonHTML = '';
                                        
//                                             if (isTargetItem && item.child_status === 'Ready for Pickup') {
//                                                 buttonHTML = `
//                                                     <div class="btn-group">
//                                                         <div class="dropdown">
//                                                             <button class="btn btn-secondary btn-sm dropdown-toggle" type="button" id="dropdownMenuButton" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="background-color: #3498db; color: white;">
//                                                                 Actions
//                                                             </button>
//                                                             <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
//                                                                 <button class="dropdown-item picked-up-button" data-item-code="${item.item_code}" data-id="${item.name}" data-name="${item.item_name}">Picked Up</button>
//                                                             </div>
//                                                         </div>
//                                                     </div>
//                                                 `;
//                                             } else if (isTargetItem && item.child_status === 'Picked Up') {
//                                                 buttonHTML = `
//                                                     <div class="btn-group">
//                                                         <div class="dropdown">
//                                                             <button class="btn btn-info btn-sm dropdown-toggle" type="button" id="dropdownMenuButton" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="z-index: 1; background-color: #3498db;">
//                                                                 Actions
//                                                             </button>
//                                                             <div class="dropdown-menu" aria-labelledby="dropdownMenuButton">
//                                                                 <button class="dropdown-item submitted-to-office-button" data-item-code="${item.item_code}" data-id="${item.name}" data-name="${item.item_name}">Submitted to Office</button>
                                                                
//                                                             </div>
//                                                         </div>
//                                                     </div>
//                                                 `;
//                                             }
                                        
//                                             return `
//                                                 <tr style="background-color: ${isTargetItem ? '#e0f7fa' : 'transparent'};">
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${item.item_code}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${item.item_name}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${item.child_status}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">
//                                                         ${buttonHTML ? buttonHTML : ''}
//                                                     </td>
//                                                 </tr>
//                                             `;
//                                         }).join('')}
//                                     </tbody>
//                                     </table>

//                                 </div>
                                

//                                 <!-- Payment and Journal Entries Table -->
//                                  <!-- Check the payment status and show the button for creating payment entry if necessary -->
//                                     ${(r.message.rental_payment_status === "Partially Paid" || 
//                                           r.message.rental_payment_status === "Unpaid" || 
//                                           r.message.security_deposit_payment_status === "Unpaid" || 
//                                           r.message.security_deposit_payment_status === "Partially Paid") && 
//                                           frm.doc.status == "Assigned" ? `
//                                         <div style="text-align: right; ">
//                                             <button class="btn-create-payment" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                                 Create Payment Entry
//                                             </button>
//                                         </div>
//                                     ` : ''}
//                                 <div>
//                                     <h4 style="color: #333;">Payment and Journal Entries</h4>
//                                     <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
//                                         <thead>
//                                             <tr>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Type</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Entry ID</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Posting Date</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Amount</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Status</th>
//                                                 <th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2; text-align: left;">Action</th>
//                                             </tr>
//                                         </thead>
//                                         <tbody>
//                                             ${r.message.payment_entries.map(entry => `
//                                                 <tr>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">Payment Entry</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">
//                                                                     ${frappe.user.has_role("NHK Admin") ? `<a href="/app/payment-entry/${entry.name}" target="_blank">${entry.name}</a>` : `${entry.name}`}
//                                                                 </td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${entry.posting_date}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(entry.amount)}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${entry.status}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">
//                                                         ${entry.status === "Draft" && frappe.user.has_role("NHK Admin") ? `
//                                                             <button class="btn-submit" data-entry-name="${entry.name}" data-doctype="Payment Entry" style="padding: 5px 10px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                                                 Submit
//                                                             </button>
//                                                         ` : ''}
//                                                     </td>
//                                                 </tr>
//                                             `).join('')}
//                                             ${r.message.journal_entries.map(entry => `
//                                                 <tr>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">Journal Entry</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">
//                                                                     ${frappe.user.has_role("NHK Admin") ? `<a href="/app/journal-entry/${entry.name}" target="_blank">${entry.name}</a>` : `${entry.name}`}
//                                                                 </td>                                                    <td style="border: 1px solid #ddd; padding: 8px;">${entry.posting_date}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(entry.amount)}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">${entry.status}</td>
//                                                     <td style="border: 1px solid #ddd; padding: 8px;">
//                                                         ${entry.status === "Draft" && frappe.user.has_role("NHK Admin") ? `
//                                                             <button class="btn-submit" data-entry-name="${entry.name}" data-doctype="Journal Entry" style="padding: 5px 10px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
//                                                                 Submit
//                                                             </button>
//                                                         ` : ''}
//                                                     </td>
//                                                 </tr>
//                                             `).join('')}
//                                         </tbody>



//                                     </table>
                                    
//                                 </div>
//                             </div>
                            
//                             <!-- Paid and Unpaid Amounts for Rental and Security Deposit -->
//                           <div style="display: flex; justify-content: space-between; margin-top: 20px; font-family: Arial, sans-serif; color: #202124; flex-wrap: wrap;">
//                                     <div style="flex: 1; padding-right: 20px; min-width: 250px; box-sizing: border-box;">
//                                         <h4 style="color: black; font-weight: 600; margin-bottom: 10px;">Rental Payment Status</h4>
//                                         <p style="margin: 5px 0;"><strong>Paid Rental Amount:</strong> <span style="color: #3c4043;">${formatted_paid_rental}</span></p>
//                                         <p style="margin: 5px 0;"><strong>Unpaid Rental Amount:</strong> <span style="color: #ea4335;">${formatted_unpaid_rental}</span></p>
//                                         <p style="margin: 5px 0;"><strong>Rental Payment Status:</strong> <span style="color: #3c4043;">${r.message.rental_payment_status}</span></p>
//                                     </div>
//                                     <div style="flex: 1; min-width: 250px; box-sizing: border-box; ">
//                                         <h4 style="color: black; font-weight: 600; margin-bottom: 10px;">Security Deposit Payment Status</h4>
//                                         <p style="margin: 5px 0;"><strong>Paid Security Deposit Amount:</strong> <span style="color: #3c4043;">${formatted_paid_security_deposit}</span></p>
//                                         <p style="margin: 5px 0;"><strong>Unpaid Security Deposit Amount:</strong> <span style="color: #ea4335;">${formatted_unpaid_security_deposit}</span></p>
//                                         <p style="margin: 5px 0;"><strong>Security Deposit Payment Status:</strong> <span style="color: #3c4043;">${r.message.security_deposit_payment_status}</span></p>
//                                     </div>
//                                 </div>

//                             </div>
                            
//                             `;
                
                        

//                         // Set the HTML content in the sales_order_html field
//                         frm.fields_dict['sales_order_html'].html(sales_order_html);
                        
                        
//                         // Add event listeners for dropdown and action buttons
//                         // Add event listeners for action buttons
//                         const pickedUpButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.picked-up-button');
//                         const backToActiveButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.back-to-active-button');
                        
//                         pickedUpButtons.forEach(button => {
//                             button.addEventListener('click', () => {
//                                 const sales_order_id = frm.doc.sales_order_id
//                                 const itemCode = button.getAttribute('data-item-code');
//                                 const itemName = button.getAttribute('data-name');
//                                 const sales_order_item_id = button.getAttribute('data-id');
//                                 // console.log(itemCode, itemName,sales_order_id,sales_order_item_id)
//                                 updateStatusToPickedUp(itemCode,sales_order_id,sales_order_item_id); // Replace with your function to handle 'Picked Up'
//                             });
//                         });
                        
//                         const submittedToofficeButtons = frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.submitted-to-office-button');

//                         submittedToofficeButtons.forEach(button => {
//                             button.addEventListener('click', () => {
//                                 const sales_order_id = frm.doc.sales_order_id
//                                 const itemCode = button.getAttribute('data-item-code');
//                                 const itemName = button.getAttribute('data-name');
//                                 const sales_order_item_id = button.getAttribute('data-id');
//                                 // console.log(itemCode, itemName,sales_order_id,sales_order_item_id)
//                                 promptForDateTimeForOfficeSubmission(itemCode, sales_order_id,sales_order_item_id);
//                             });
//                         });
                        
                        
//                         // Add event listener for the Create Payment Entry button
//                         const createPaymentButton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-create-payment');
//                         if (createPaymentButton) {
//                             createPaymentButton.addEventListener('click', () => {
//                                 create_payment_entry(r.message, frm.doc.sales_order_id,frm.doc.technician_id,frm.doc.name); // Pass the entire sales order details
//                             });
//                         }
                        
//                             // Add event listener for the Dispatched button
//                             const dispatchButton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-dispatched');
//                             if (dispatchButton) {
//                                 dispatchButton.addEventListener('click', () => {
//                                     change_sales_order_status_dispatched(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
//                                 });
//                             }
                            
                            
//                             const deliveredbutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-delivered');
//                             if (deliveredbutton) {
//                                 deliveredbutton.addEventListener('click', () => {
//                                     change_sales_order_status_delivered(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
//                                 });
//                             }
                        
                        
//                             const pickupbutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-pickup');
//                             if (pickupbutton) {
//                                 pickupbutton.addEventListener('click', () => {
//                                     console.log(r.message, frm.doc.sales_order_id)
//                                     change_sales_order_status_pickup(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
//                                 });
//                             }
                            
//                             const submittiofficebutton = frm.fields_dict['sales_order_html'].wrapper.querySelector('.btn-submit_to_office');
//                             if (submittiofficebutton) {
//                                 submittiofficebutton.addEventListener('click', () => {
//                                     console.log(r.message, frm.doc.sales_order_id)
//                                     change_sales_order_status_submit_to_office(r.message, frm.doc.sales_order_id); // Pass the entire sales order details
//                                 });
//                             }
                        
//                         frm.fields_dict['sales_order_html'].wrapper.querySelectorAll('.btn-submit').forEach(button => {
//                             button.addEventListener('click', () => {
//                                 const entryName = button.getAttribute('data-entry-name');
//                                 const doctype = button.getAttribute('data-doctype');
//                                 submitEntry(entryName, doctype);  // Call the submit function with entry details
//                             });
//                         });
//                     }
//                 }
//             });
//         }
//     }
// });

// // Function to prompt for datetime and execute method for submission to office
// function promptForDateTimeForOfficeSubmission(itemCode, sales_order_id,sales_order_item_id) {
//     frappe.confirm(
//         'Are you sure you want to mark this item as Submitted to Office?', // Confirmation message
//         function() {
//             frappe.prompt([
//                 {
//                     fieldname: 'submission_datetime',
//                     fieldtype: 'Datetime',
//                     label: 'Submission Datetime',
//                     default:'Now',
//                     reqd: 1
//                 }
//             ], function(values) {
//                 var submissionDatetime = values.submission_datetime;
//                 // console.log("Submission Datetime:", submissionDatetime, itemCode1,docname,name);
//                 // Call a function to execute method for submission to office
//                 updateStatusToSubmittedToOffice(itemCode, submissionDatetime,sales_order_id,sales_order_item_id);
//             }, 'Enter Submission Datetime', 'Submit');
//         },
//         function() {
//             // If user cancels, do nothing
//         }
//     );
// }


// // Function to update status to Submitted to Office
// function updateStatusToSubmittedToOffice(itemCode, submissionDatetime,sales_order_id,sales_order_item_id) {
//     frappe.call({
//         method: 'erpnext.selling.doctype.sales_order.sales_order.update_status_to_submitted_to_office',
//         args: {
//             item_code: itemCode,
//             submission_datetime: submissionDatetime,
//             docname: sales_order_id,
//             child_name:sales_order_item_id
//         },
//         callback: function(response) {
//             if (response.message) {
//                 // Success message
//                 frappe.msgprint("Item status updated to Submitted to Office successfully.");
//                 setTimeout(() => {
//                     window.location.reload();
//                 }, 3000); // 3000 milliseconds = 1 second
//             } else {
//                 // Error message
//                 frappe.msgprint("Failed to update item status to Submitted to Office.");
//             }
//         }
//     });
// }

// function updateStatusToPickedUp(itemCode,sales_order_id,sales_order_item_id) {
    
//     frappe.confirm(
//         'Are you sure you want to mark this item as Picked Up?', // Confirmation message
//         function() {
//             frappe.prompt([
//                 {
//                     fieldname: 'picked_up_datetime',
//                     fieldtype: 'Datetime',
//                     label: 'Picked Up Datetime',
//                     default:'Now',
//                     reqd: 1
//                 }
//             //   {
//             //         fieldname: 'technician_name',
//             //         fieldtype: 'Link',
//             //         options: 'Technician Details',
//             //         label: 'Technician Name',
//             //         reqd: 1,
//             //         onchange: function() {
//             //             // Function to dynamically update technician mobile based on selected technician
//             //             var technicianName = this.value;
//             //             if (technicianName) {
//             //                 frappe.call({
//             //                     method: 'frappe.client.get_value',
//             //                     args: {
//             //                         doctype: 'Technician Details',
//             //                         filters: { 'name': technicianName },
//             //                         fieldname: ['mobile_number']
//             //                     },
//             //                     callback: function(response) {
//             //                         if (response.message && response.message.mobile_number) {
//             //                             // Set the value of technician mobile
//             //                             cur_dialog.fields_dict.technician_mobile.set_input(response.message.mobile_number);
//             //                         }
//             //                     }
//             //                 });
//             //             }
//             //         }
//             //     },
//             //     {
//             //         fieldname: 'technician_mobile',
//             //         fieldtype: 'Data',
//             //         label: 'Technician Mobile Number',
//             //         // reqd: 1
//             //     }



//             ], function(values) {
//                 var picked_up_datetime = values.picked_up_datetime;
//                 // var technicianMobile = values.technician_mobile;
                
//                 // Call a function to update status to Picked Up
//                 frappe.call({
//                     method: 'erpnext.selling.doctype.sales_order.sales_order.update_status_to_picked_up',
//                     args: {
//                         item_code: itemCode,
//                         docname: sales_order_id,
//                         child_name: sales_order_item_id,
//                         picked_up_datetime: picked_up_datetime
//                     },
//                     callback: function(response) {
//                         if (response.message) {
//                             // Success message
//                             frappe.msgprint("Item picked up successfully.");
//                             setTimeout(() => {
//                                 window.location.reload();
//                             }, 3000); // 3000 milliseconds = 1 second
//                         } else {
//                             // Error message
//                             frappe.msgprint("Failed to update item status.");
//                         }
//                     }
//                 });
//             }, 'Enter Technician Details', 'Submit');
//         },
//         function() {
//             // If user cancels, do nothing
//         }
//     );
// }



// function submitEntry(entryName, doctype) {
//     frappe.confirm(
//         `Are you sure you want to submit the ${doctype} entry: ${entryName}?`,
//         function() {
//             // If the user confirms, submit the entry
//             frappe.call({
//                 method: "nhk.custom_script.submit_entry", // Update with your actual app and method path
//                 args: {
//                     entry_name: entryName,
//                     doctype: doctype
//                 },
//                 callback: function(response) {
//                     if (response.message) {
//                         frappe.show_alert({ 
//                             message: response.message.message,  // Correctly accessing the message property
//                             indicator: 'green' 
//                         });
//                         setTimeout(() => {
//         						window.location.reload();
//         					}, 1000);
//                         // Optionally, refresh the page or update the table to reflect the changes
//                         // location.reload(); // Uncomment to refresh the page
//                     } else {
//                         frappe.show_alert({ message: 'Error submitting entry.', indicator: 'red' });
//                     }
//                 },
//                 error: function(error) {
//                     frappe.show_alert({ message: 'Error submitting entry: ' + error.message, indicator: 'red' });
//                 }
//             });
//         },
//         function() {
//             // If the user cancels, show a cancel alert
//             frappe.show_alert({ message: 'Submission canceled.', indicator: 'orange' });
//         }
//     );
// }



// function change_sales_order_status_submit_to_office(salesOrderDetails, salesOrderId) {
//     console.log(salesOrderDetails, salesOrderId);
    
//     // Check if items exist and is an array before mapping
//     let itemCodes = Array.isArray(salesOrderDetails.items) ? salesOrderDetails.items.map(item => item.item_code) : [];
//     console.log(itemCodes);
    
//     // Prompt for the submitted date
//     frappe.prompt([
//         {
//             label: 'Submitted Date',
//             fieldname: 'submitted_date',
//             fieldtype: 'Datetime',
//             default: frappe.datetime.now_datetime(),
//             reqd: 1
//         }
//     ], (values) => {
//         // Call the server method to update Sales Order with the entered values
//         frappe.call({
//             method: "erpnext.selling.doctype.sales_order.sales_order.make_submitted_to_office",
//             args: {
//                 docname: salesOrderId,
//                 item_code: itemCodes,
//                 submitted_date: values.submitted_date
//             },
//             callback: function(response) {
//                 if (response.message) {
//                     frappe.msgprint("Sales Order status has been updated to Submitted to Office!");
//                     setTimeout(() => {
//                         window.location.reload();
//                     }, 1000);
//                 } else {
//                     frappe.msgprint("Error: " + response.message);
//                 }
//             }
//         });
//     }, __('Submitted to Office'));
// }





// function change_sales_order_status_pickup(salesOrderDetails, salesOrderId) {
//     // Prompt for the delivered date and other necessary details
//     frappe.prompt([
        
//         {
// 				label: 'Pick Up Date and Time',
// 				fieldname: 'pickup_date',
// 				fieldtype: 'Datetime',
//                 default: frappe.datetime.now_datetime(),
// 				reqd: 1
// 			}
//     ], (values) => {
//         // Update Sales Order with the entered values
//         frappe.call({
//             method: "erpnext.selling.doctype.sales_order.sales_order.make_pickedup", // Update this to your server method
//             args: {
//                 docname: salesOrderId,
//                 pickup_date: values.pickup_date
                
//             },
//             callback: function(response) {
//                 if (response.message) {
//                     frappe.msgprint("Sales Order status has been updated to Pick Up!");
//                     setTimeout(() => {
//         						window.location.reload();
//         					}, 1000);
                   
//                 } else {
//                     frappe.msgprint("Error: " + response.message);
//                 }
//             }
//         });
//     }, __('Picked Up'));
// }

// function change_sales_order_status_delivered(salesOrderDetails, salesOrderId) {
//     // Prompt for the delivered date and other necessary details
//     frappe.prompt([
//         {
//             label: 'Delivered Date',
//             fieldname: 'delivered_date',
//             fieldtype: 'Datetime',
//             default: frappe.datetime.now_datetime(), // Default to today's date
//             reqd: 1
//         },
//         {
//             fieldtype: 'Section Break'
//         },
//         {
//             label: 'Payment Status',
//             fieldname: 'payment_status',
//             fieldtype: 'Data',
//             default: salesOrderDetails.payment_status,
//             read_only: 1
//         },
//         {
//             label: 'Balance Amount',
//             fieldname: 'balance_amount',
//             fieldtype: 'Currency',
//             default: salesOrderDetails.balance_amount,
//             read_only: 1
//         },
//         {
//             label: 'Payment Received Amount',
//             fieldname: 'received_amount',
//             fieldtype: 'Currency',
//             default: salesOrderDetails.received_amount,
//             read_only: 1
//         },
//         {
//             fieldtype: 'Column Break'
//         },
//         {
//             label: 'Security Deposit Payment Status',
//             fieldname: 'security_deposit_payment_status',
//             fieldtype: 'Data',
//             default: salesOrderDetails.security_deposit_status,
//             read_only: 1
//         },
//         {
//             label: 'Payment Outstanding Security Deposit Amount',
//             fieldname: 'outstanding_security_deposit_amount',
//             fieldtype: 'Currency',
//             default: salesOrderDetails.outstanding_security_deposit_amount,
//             read_only: 1
//         },
//         {
//             label: 'Received Security Deposit Amount',
//             fieldname: 'paid_security_deposite_amount',
//             fieldtype: 'Currency',
//             default: salesOrderDetails.paid_security_deposite_amount,
//             read_only: 1
//         },
//         {
//             fieldtype: 'Section Break'
//         },
//         {
//             label: 'Payment Pending Reason',
//             fieldname: 'payment_pending_reason',
//             fieldtype: 'Link',
//             options: 'Payment Pending Reason',
//             depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")',
//             mandatory_depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")'
//         },
//         {
//             label: 'Notes',
//             fieldname: 'notes',
//             fieldtype: 'Small Text',
//             depends_on: 'eval: (doc.payment_status == "UnPaid" || doc.payment_status == "Partially Paid") || (doc.security_deposit_payment_status == "Unpaid" || doc.security_deposit_payment_status == "Partially Paid")',
//         },
//         {
//             label: 'Rental Order Agreement Attachment',
//             fieldname: 'rental_order_agreement_attachment',
//             fieldtype: 'Attach',
//         },
//         {
//             label: 'Aadhar Card Attachment',
//             fieldname: 'aadhar_card_attachment',
//             fieldtype: 'Attach',
//         }
//     ], (values) => {
//         // Update Sales Order with the entered values
//         frappe.call({
//             method: "erpnext.selling.doctype.sales_order.sales_order.make_delivered", // Update this to your server method
//             args: {
//                 docname: salesOrderId,
//                 customer_name:salesOrderDetails.customer,
//                 delivered_date: values.delivered_date,
//                 payment_pending_reason: values.payment_pending_reason,
//                 rental_order_agreement_attachment: values.rental_order_agreement_attachment,
//             	aadhar_card_attachment: values.aadhar_card_attachment,
//                 notes: values.notes,
                
//             },
//             callback: function(response) {
//                 if (response.message) {
//                     frappe.msgprint("Sales Order status has been updated to DELIVERED!");
//                     setTimeout(() => {
//         						window.location.reload();
//         					}, 1000);
                   
//                 } else {
//                     frappe.msgprint("Error: " + response.message);
//                 }
//             }
//         });
//     }, __('DELIVERED'));
// }




// function change_sales_order_status_dispatched(salesOrderDetails, salesOrderId) {
//     frappe.confirm(
//         'Are you sure you want to change the status of this order to DISPATCHED?',
//         () => {
//             // Prompt for the dispatch date
//             frappe.prompt([
//                 {
//                     fieldname: 'dispatch_date',
//                     fieldtype: 'Date',
//                     label: 'Dispatch Date',
//                     reqd: 1,
//                     default: frappe.datetime.nowdate() // Set default to today's date
//                 }
//             ],
//             function(values) {
//                 // Call server method to update the sales order status with dispatch date
//                 frappe.call({
//                     method: "erpnext.selling.doctype.sales_order.sales_order.make_dispatch",
//                     args: {
//                         docname: salesOrderId,
//                         // new_status: "DISPATCHED",
//                         dispatch_date: values.dispatch_date // Include dispatch date in the args
//                     },
//                     callback: function(response) {
//                         if (response.message) {
//                             frappe.msgprint("Sales Order status has been updated to DISPATCHED with dispatch date: " + values.dispatch_date);
//                             // Optionally refresh the form to reflect the updated status
//                             setTimeout(() => {
//         						window.location.reload();
//         					}, 1000);
                            
//                         } else {
//                             frappe.msgprint("Error: " + response.message);
//                         }
//                     }
//                 });
//             },
//             'Enter Dispatch Date', // Title for the prompt
//             'Dispatch' // Button label for the prompt
//             );
//         }
//     );
// }



// // JavaScript function to handle the payment entry creation
// function create_payment_entry(sales_order_details, sales_order_id,technician_id,technician_visit_id) {
//     // Open prompt to get customer payment details
//     frappe.prompt([ {
//             fieldname: 'customer_name',
//             fieldtype: 'Link',
//             options: 'Customer',
//             label: 'Customer Name',
//             read_only: 1,
//             default: sales_order_details.customer
//         },
//         {
//             fieldname: 'rental_payment_amount',
//             fieldtype: 'Currency',
//             label: 'Rental Payment Balance Amount',
//             default: sales_order_details.unpaid_rental_amount
//         },
//         {
//             fieldname: 'security_deposit_payment_amount',
//             fieldtype: 'Currency',
//             label: 'Security Deposit Balance Amount',
//             default: sales_order_details.unpaid_security_deposit_amount
//         },
//         {
//             fieldname: 'reference_no',
//             fieldtype: 'Data',
//             label: 'Cheque/Reference No',
//             depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"',
//             mandatory_depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"'
//         },
//         {
//             fieldtype: 'Column Break'
//         },
//         {
//             fieldname: 'payment_date',
//             fieldtype: 'Date',
//             label: 'Payment Date',
//             default: 'Today',
//             reqd: 1
//         },
//         {
//             fieldname: 'mode_of_payment',
//             fieldtype: 'Link',
//             options: 'Mode of Payment',
//             label: 'Mode Of Payment',
//             mandatory_depends_on: 'eval:doc.rental_payment_amount || doc.security_deposit_payment_amount',
//             reqd: 1,
//             onchange: function() {
//                 var selectedModeOfPayment = this.value;
//                 if (selectedModeOfPayment) {
//                     frappe.call({
//                         method: 'erpnext.selling.doctype.sales_order.sales_order.get_default_account',
//                         args: {
//                             mode_of_payment: selectedModeOfPayment
//                         },
//                         callback: function(response) {
//                             if (response.message) {
//                                 if (cur_dialog.fields_dict.rental_payment_amount.get_value() > 0) {
//                                     cur_dialog.fields_dict.payment_account.set_input(response.message.default_account);
//                                 }
//                                 if (cur_dialog.fields_dict.security_deposit_payment_amount.get_value() > 0) {
//                                     cur_dialog.fields_dict.security_deposit_account.set_input(response.message.journal_entry_default_account);
//                                 }
//                             }
//                         }
//                     });
//                 }
//             }
//         },
//         {
//             fieldname: 'payment_account',
//             fieldtype: 'Data',
//             label: 'Payment Account',
//             depends_on: 'eval:doc.rental_payment_amount',
//             read_only: 1
//         },
//         {
//             fieldname: 'security_deposit_account',
//             fieldtype: 'Data',
//             label: 'Security Deposit Account',
//             depends_on: 'eval:doc.security_deposit_payment_amount',
//             read_only: 1
//         },
//         {
//             fieldname: 'reference_date',
//             fieldtype: 'Date',
//             label: 'Cheque/Reference Date',
//             depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"',
//             mandatory_depends_on: 'eval:doc.mode_of_payment == "Bank Draft" || doc.mode_of_payment == "Kotak Bank" || doc.mode_of_payment == "Razorpay"'
//         },
//         {
//             fieldtype: 'Section Break'
//         },
//         {
//             fieldname: 'remark',
//             fieldtype: 'Small Text',
//             label: 'Remark',
//             description: 'Enter your remark here',
//             placeholder: 'Remark',
//             reqd: false
//         }], function(values) {
//         // Call process_payment with all the collected parameters
//         frappe.call({
//             method: 'erpnext.selling.doctype.sales_order.sales_order.process_payment',
//             args: {
//                 balance_amount: sales_order_details.balance_amount,
//                 outstanding_security_deposit_amount: sales_order_details.outstanding_security_deposit_amount,
//                 customer_name: values.customer_name,
//                 rental_payment_amount: values.rental_payment_amount,
//                 sales_order_name: sales_order_id,                // Sales Order ID
//                 master_order_id: sales_order_details.master_order_id, // Master Order ID from sales order details
//                 security_deposit_status: sales_order_details.security_deposit_status, // Security Deposit Status
//                 customer: sales_order_details.customer,           // Customer Name
//                 payment_account: values.payment_account,          // Payment Account from prompt (if added)
//                 security_deposit_account: values.security_deposit_account, // Security Deposit Account (if added)
//                 reference_no: values.reference_no,
//                 reference_date: values.reference_date,
//                 mode_of_payment: values.mode_of_payment,
//                 payment_date: values.payment_date,
//                 security_deposit_payment_amount: values.security_deposit_payment_amount,
//                 remark: values.remark,
//                 from_technician_portal:1,
//                 technician_id:technician_id,
//                 technician_visit_id:technician_visit_id
//             },
//             callback: function(response) {
//                 if (response.message) {
//                     frappe.msgprint("Payment processed successfully!");
//                     setTimeout(() => {
// 						window.location.reload();
// 					}, 1000);
//                 } else {
//                     frappe.msgprint("Error processing payment: " + response.message);
//                 }
//             }
//         });
//     }, 'Enter Payment Details', 'Make Payment');
// }
