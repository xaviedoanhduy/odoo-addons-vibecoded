This module extends the Authorize.net payment provider to allow adding
payment cards to partners via direct Customer/Payment Profile creation
in Authorize.net, without triggering the \$0.01 validation transaction.

The standard Odoo flow for saving payment methods requires a validation
transaction that charges \$0.01 (or equivalent) to verify the card. This
module provides an alternative approach that creates Customer and
Payment Profiles directly using Accept.js opaque data, avoiding any
charges.

Features:

- Smart button "Add a Card" on Partner Form
- New endpoint `/user/payment_method2/` for the add card page
- New endpoint `/payment/profile` for direct profile creation
- Extended AuthorizeAPI with methods for Customer/Payment Profile
  management
- Frontend JavaScript for handling Accept.js opaque data submission
- No validation transaction or charges required
