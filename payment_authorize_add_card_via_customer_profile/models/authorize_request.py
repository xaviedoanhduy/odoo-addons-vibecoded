# Copyright 2024 Kencove
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from uuid import uuid4

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_authorize.models.authorize_request import AuthorizeAPI

_logger = logging.getLogger(__name__)


def create_customer_profile_direct(self, partner):
    """Create a customer profile directly without a transaction.

    This allows creating a customer profile in Authorize.net for storing
    payment methods without requiring an initial transaction.

    :param recordset partner: the res.partner record of the customer
    :return: the customerProfileId if successful, False otherwise
    :rtype: str or False
    """
    merchant_id = f"ODOO-{partner.id}-{uuid4().hex[:8]}"[:20]
    # Note: Authorize.net API requires fields in specific order per XSD schema:
    # merchantCustomerId, description, email, paymentProfiles, shipToList, profileType
    response = self._make_request(
        "createCustomerProfileRequest",
        {
            "profile": {
                "merchantCustomerId": merchant_id,
                "description": f"Odoo Partner: {partner.display_name[:50]}",
                "email": partner.email or "",
            },
        },
    )

    if response.get("err_code"):
        _logger.warning(
            "Failed to create customer profile for partner %(partner)s: %(error)s",
            {"partner": partner.id, "error": response.get("err_msg")},
        )
        return False

    customer_profile_id = response.get("customerProfileId")
    if not customer_profile_id:
        _logger.warning(
            "No customerProfileId returned when creating profile for partner %s",
            partner.id,
        )
        return False

    _logger.info(
        "Created customer profile %(profile_id)s for partner %(partner)s",
        {"profile_id": customer_profile_id, "partner": partner.id},
    )
    return customer_profile_id


def create_customer_payment_profile(self, customer_profile_id, opaque_data, partner):
    """Create a customer payment profile using opaque data from Accept.js.

    This creates a payment profile under an existing customer profile
    using the opaque data (payment nonce) obtained from Accept.js,
    without requiring a transaction.

    :param str customer_profile_id: The Authorize.net customer profile ID
    :param dict opaque_data: The opaque data from Accept.js containing
                             dataDescriptor and dataValue
    :param recordset partner: the res.partner record for billing info
    :return: dict with payment_profile_id and payment_details, or False on error
    :rtype: dict or False
    """
    # Build billTo from partner
    if partner.is_company:
        split_name = "", partner.name
    else:
        split_name = payment_utils.split_partner_name(
            partner.name or partner.display_name
        )

    bill_to = {
        "firstName": split_name[0][:50] if split_name[0] else "",
        "lastName": split_name[1][:50] if split_name[1] else partner.name[:50],
        "company": partner.name[:50] if partner.is_company else "",
        "address": ((partner.street or "") + " " + (partner.street2 or "")).strip()[
            :60
        ],
        "city": partner.city or "",
        "state": partner.state_id.name[:40] if partner.state_id else "",
        "zip": partner.zip or "",
        "country": partner.country_id.name[:60] if partner.country_id else "",
    }

    response = self._make_request(
        "createCustomerPaymentProfileRequest",
        {
            "customerProfileId": customer_profile_id,
            "paymentProfile": {
                "billTo": bill_to,
                "payment": {
                    "opaqueData": opaque_data,
                },
            },
            "validationMode": "liveMode" if self.state == "enabled" else "testMode",
        },
    )

    if response.get("err_code"):
        _logger.warning(
            "Failed to create payment profile for customer %(profile)s: %(error)s",
            {"profile": customer_profile_id, "error": response.get("err_msg")},
        )
        return {
            "error": True,
            "error_msg": response.get("err_msg", "Unknown error"),
        }

    payment_profile_id = response.get("customerPaymentProfileId")
    if not payment_profile_id:
        _logger.warning(
            "No customerPaymentProfileId returned for customer profile %s",
            customer_profile_id,
        )
        return {
            "error": True,
            "error_msg": "No payment profile ID returned",
        }

    # Get the payment profile details to obtain card info
    details_response = self._make_request(
        "getCustomerPaymentProfileRequest",
        {
            "customerProfileId": customer_profile_id,
            "customerPaymentProfileId": payment_profile_id,
            "unmaskExpirationDate": True,
        },
    )

    if details_response.get("err_code"):
        _logger.warning(
            "Created payment profile but failed to get details: %s",
            details_response.get("err_msg"),
        )
        # Return partial success - we have the profile but not the details
        return {
            "profile_id": customer_profile_id,
            "payment_profile_id": payment_profile_id,
            "payment_details": "****",
        }

    payment = details_response.get("paymentProfile", {}).get("payment", {})
    credit_card = payment.get("creditCard", {})
    bank_account = payment.get("bankAccount", {})

    if self.payment_method_type == "credit_card":
        payment_details = credit_card.get("cardNumber", "")[-4:] or "****"
    else:
        payment_details = bank_account.get("accountNumber", "")[-4:] or "****"

    _logger.info(
        "Created payment profile %(pp_id)s under customer profile %(cp_id)s",
        {"pp_id": payment_profile_id, "cp_id": customer_profile_id},
    )

    return {
        "profile_id": customer_profile_id,
        "payment_profile_id": payment_profile_id,
        "payment_details": payment_details,
    }


def get_or_create_customer_profile(self, partner, provider):
    """Get existing customer profile for partner or create a new one.

    This looks for an existing payment token for the partner to reuse
    the customer profile, or creates a new one if none exists.

    :param recordset partner: the res.partner record
    :param recordset provider: the payment.provider record
    :return: the customerProfileId
    :rtype: str or False
    """
    # Check if partner already has a token with an authorize_profile
    existing_token = (
        partner.env["payment.token"]
        .sudo()
        .search(
            [
                ("partner_id", "=", partner.id),
                ("provider_id", "=", provider.id),
                ("authorize_profile", "!=", False),
            ],
            limit=1,
        )
    )

    if existing_token and existing_token.authorize_profile:
        _logger.info(
            "Reusing existing customer profile %(profile)s for partner %(partner)s",
            {"profile": existing_token.authorize_profile, "partner": partner.id},
        )
        return existing_token.authorize_profile

    # Create a new customer profile
    return self.create_customer_profile_direct(partner)


# Monkey-patch the AuthorizeAPI class
AuthorizeAPI.create_customer_profile_direct = create_customer_profile_direct
AuthorizeAPI.create_customer_payment_profile = create_customer_payment_profile
AuthorizeAPI.get_or_create_customer_profile = get_or_create_customer_profile
