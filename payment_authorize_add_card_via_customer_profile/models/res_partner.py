# Copyright 2024 Kencove
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from werkzeug.urls import url_encode

from odoo import _, api, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _validate_partner_for_payment(self):
        """Validate partner has required fields for payment profile creation."""
        self.ensure_one()
        missing_fields = []
        if not self.street:
            missing_fields.append(_("Street"))
        if not self.zip:
            missing_fields.append(_("Zip"))
        if not self.city:
            missing_fields.append(_("City"))
        if missing_fields:
            raise UserError(
                _("Customer is missing required address fields:\n%s")
                % "\n".join(missing_fields)
            )

    def action_add_card_via_profile(self):
        """Open the Add Card page using Customer Profile method (no $0.01 transaction).

        This action opens a special payment method page that creates
        Customer/Payment Profiles directly in Authorize.net without
        triggering the validation transaction.
        """
        self.ensure_one()
        self._validate_partner_for_payment()

        values_to_pass = {
            "model": self._name,
            "id": self.id,
            "company_id": self.env.company.id,
        }

        final_url = f"/user/payment_method2/{self.id}/?{url_encode(values_to_pass)}"
        return {
            "type": "ir.actions.act_url",
            "url": final_url,
            "target": "self",
        }
