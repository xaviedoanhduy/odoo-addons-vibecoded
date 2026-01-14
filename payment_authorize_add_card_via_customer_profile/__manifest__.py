# Copyright 2024 Kencove
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Payment Authorize.net - Add Card via Customer Profile",
    "version": "16.0.1.0.0",
    "summary": """
Add payment cards to partners via direct Customer/Payment Profile creation
in Authorize.net, without triggering the $0.01 validation transaction.
    """,
    "author": "Kencove, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/account-payment",
    "category": "Accounting/Payment Providers",
    "depends": [
        "payment_authorize",
    ],
    "data": [
        "views/res_partner_view.xml",
        "views/payment_authorize_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "payment_authorize_add_card_via_customer_profile/static/src/js/payment_form.js",
        ],
    },
    "license": "AGPL-3",
    "installable": True,
}
