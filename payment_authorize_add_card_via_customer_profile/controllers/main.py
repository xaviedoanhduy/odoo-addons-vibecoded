# Copyright 2024 Kencove
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import pprint

from werkzeug.urls import url_encode

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_authorize.controllers.main import AuthorizeController
from odoo.addons.payment_authorize.models.authorize_request import AuthorizeAPI

_logger = logging.getLogger(__name__)


class AddCardViaProfileController(AuthorizeController):
    """Controller for adding cards via Customer Profile creation.

    This controller provides endpoints to add payment cards to partners
    by directly creating Customer/Payment Profiles in Authorize.net,
    avoiding the $0.01 validation transaction.
    """

    @http.route(
        ["/user/payment_method2/<model('res.partner'):partner>"],
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
    )
    def payment_method_via_profile(self, partner, **kwargs):
        """Render the Add Card page for direct profile creation.

        This page allows users to enter card details which will be tokenized
        via Accept.js and then used to create Customer/Payment Profiles
        directly in Authorize.net.

        :param record partner: The partner to add the payment method to
        :return: Rendered payment method page
        """
        company_id = kwargs.get("company_id")
        if company_id is None:
            company_id = request.env.company.id

        # Get providers that support tokenization (Authorize.net only for now)
        providers_sudo = (
            request.env["payment.provider"]
            .sudo()
            ._get_compatible_providers(
                int(company_id),
                partner.id,
                0.0,
                force_tokenization=True,
                is_validation=True,
            )
        )

        # Filter to only Authorize.net providers
        providers_sudo = providers_sudo.filtered(lambda p: p.code == "authorize")

        # Get existing tokens for display
        payment_tokens = partner.payment_token_ids
        payment_tokens |= partner.commercial_partner_id.sudo().payment_token_ids

        access_token = payment_utils.generate_access_token(partner.id, None, None)

        # Build return URL for after adding the card
        return_url = kwargs.get(
            "redirect",
            f"/user/payment_method2/{partner.id}/?{url_encode(dict(kwargs))}",
        )

        # Build back to record URL
        back_url = None
        model = kwargs.get("model")
        record_id = kwargs.get("id")
        if model == "res.partner" and record_id:
            action_id = request.env.ref("base.action_partner_form").id
            back_url = (
                f"/web#model={model}&id={record_id}"
                f"&action={action_id}&view_type=form"
            )

        values = {
            "tokens": payment_tokens,
            "providers": providers_sudo,
            "landing_route": return_url,
            "access_token": access_token,
            "partner_id": partner.id,
            "partner": partner,
            "back_url": back_url,
            # Custom route for profile creation (not validation transaction)
            "profile_creation_route": "/payment/profile",
        }
        return request.render(
            "payment_authorize_add_card_via_customer_profile.payment_methods_via_profile",
            values,
        )

    @http.route("/payment/profile", type="json", auth="user")
    def create_payment_profile(
        self, provider_id, partner_id, opaque_data, access_token
    ):
        """Create a Customer/Payment Profile in Authorize.net from opaque data.

        This endpoint receives the opaque data (payment nonce) from Accept.js
        and creates a Customer Profile and Payment Profile in Authorize.net,
        then creates a corresponding payment.token in Odoo.

        :param int provider_id: The payment provider (Authorize.net) ID
        :param int partner_id: The partner to create the token for
        :param dict opaque_data: The opaque data from Accept.js containing
                                 dataDescriptor and dataValue
        :param str access_token: Access token for validation
        :return: dict with success status and message
        """
        # Validate access token
        if not payment_utils.check_access_token(access_token, partner_id, None, None):
            raise ValidationError(
                _("Invalid access token. Please refresh the page and try again.")
            )

        partner = request.env["res.partner"].sudo().browse(partner_id)
        if not partner.exists():
            raise ValidationError(_("Partner not found."))

        provider = request.env["payment.provider"].sudo().browse(provider_id)
        if not provider.exists() or provider.code != "authorize":
            raise ValidationError(_("Invalid payment provider."))

        _logger.info(
            "Creating payment profile for partner %s via provider %s",
            partner_id,
            provider_id,
        )

        # Initialize the Authorize.net API
        authorize_api = AuthorizeAPI(provider)

        # Get or create customer profile
        customer_profile_id = authorize_api.get_or_create_customer_profile(
            partner, provider
        )
        if not customer_profile_id:
            _logger.error(
                "Failed to get/create customer profile for partner %s", partner_id
            )
            return {
                "success": False,
                "error": _("Failed to create customer profile in Authorize.net."),
            }

        # Create payment profile with the opaque data
        result = authorize_api.create_customer_payment_profile(
            customer_profile_id, opaque_data, partner
        )

        if result.get("error"):
            _logger.warning(
                "Failed to create payment profile: %(error)s",
                {"error": result.get("error_msg")},
            )
            return {
                "success": False,
                "error": result.get(
                    "error_msg", _("Failed to create payment profile.")
                ),
            }

        _logger.info(
            "Created payment profile, now creating token: %(result)s",
            {"result": pprint.pformat(result)},
        )

        # Create the payment token
        token = (
            request.env["payment.token"]
            .sudo()
            .create(
                {
                    "provider_id": provider.id,
                    "payment_details": result.get("payment_details", "****"),
                    "partner_id": partner.id,
                    "provider_ref": result.get("payment_profile_id"),
                    "authorize_profile": result.get("profile_id"),
                    "authorize_payment_method_type": (
                        provider.authorize_payment_method_type
                    ),
                    "verified": True,
                }
            )
        )

        _logger.info(
            "Created payment token %(token)s for partner %(partner)s",
            {"token": token.id, "partner": partner.id},
        )

        return {
            "success": True,
            "message": _("Payment method added successfully."),
            "token_id": token.id,
        }
