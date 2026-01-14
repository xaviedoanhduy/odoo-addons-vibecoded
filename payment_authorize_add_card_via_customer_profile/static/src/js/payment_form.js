/* Copyright 2024 Kencove
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
 */
/* global Accept */
odoo.define(
    "payment_authorize_add_card_via_customer_profile.payment_form",
    (require) => {
        "use strict";

        const core = require("web.core");
        const {loadJS} = require("@web/core/assets");

        const manageForm = require("payment.manage_form");

        const _t = core._t;

        /**
         * Mixin for handling payment profile creation via Authorize.net.
         *
         * This extends the manage form to support creating Customer/Payment Profiles
         * directly from card details, without going through the validation transaction flow.
         */
        const authorizeProfileMixin = {
            /**
             * Return all relevant inline form inputs based on the payment method type.
             *
             * @private
             * @param {Number} providerId - The id of the selected provider
             * @returns {Object} - An object mapping input names to their DOM elements
             */
            _getInlineFormInputs: function (providerId) {
                if (this.authorizeInfo.payment_method_type === "credit_card") {
                    return {
                        card: document.getElementById(`o_authorize_card_${providerId}`),
                        month: document.getElementById(
                            `o_authorize_month_${providerId}`
                        ),
                        year: document.getElementById(`o_authorize_year_${providerId}`),
                        code: document.getElementById(`o_authorize_code_${providerId}`),
                    };
                }
                return {
                    accountName: document.getElementById(
                        `o_authorize_account_name_${providerId}`
                    ),
                    accountNumber: document.getElementById(
                        `o_authorize_account_number_${providerId}`
                    ),
                    abaNumber: document.getElementById(
                        `o_authorize_aba_number_${providerId}`
                    ),
                    accountType: document.getElementById(
                        `o_authorize_account_type_${providerId}`
                    ),
                };
            },

            /**
             * Return the credit card or bank data to pass to Accept.dispatch.
             *
             * @private
             * @param {Number} providerId - The id of the selected provider
             * @returns {Object} - Data to pass to Accept.dispatch
             */
            _getPaymentDetails: function (providerId) {
                const inputs = this._getInlineFormInputs(providerId);
                if (this.authorizeInfo.payment_method_type === "credit_card") {
                    return {
                        cardData: {
                            cardNumber: inputs.card.value.replace(/ /g, ""),
                            month: inputs.month.value,
                            year: inputs.year.value,
                            cardCode: inputs.code.value,
                        },
                    };
                }
                return {
                    bankData: {
                        nameOnAccount: inputs.accountName.value.substring(0, 22),
                        accountNumber: inputs.accountNumber.value,
                        routingNumber: inputs.abaNumber.value,
                        accountType: inputs.accountType.value,
                    },
                };
            },

            /**
             * Prepare the inline form of Authorize.Net.
             *
             * @override
             * @private
             * @param {String} code - The provider code
             * @param {Number} paymentOptionId - The id of the selected payment option
             * @param {String} flow - The payment flow
             * @returns {Promise}
             */
            _prepareInlineForm: function (code, paymentOptionId, flow) {
                if (code !== "authorize") {
                    return this._super(...arguments);
                }

                if (flow === "token") {
                    return Promise.resolve();
                }

                this._setPaymentFlow("direct");

                let acceptJSUrl = "https://js.authorize.net/v1/Accept.js";
                return this._rpc({
                    route: "/payment/authorize/get_provider_info",
                    params: {
                        provider_id: paymentOptionId,
                    },
                })
                    .then((providerInfo) => {
                        if (providerInfo.state !== "enabled") {
                            acceptJSUrl = "https://jstest.authorize.net/v1/Accept.js";
                        }
                        this.authorizeInfo = providerInfo;
                    })
                    .then(() => {
                        loadJS(acceptJSUrl);
                    })
                    .guardedCatch((error) => {
                        error.event.preventDefault();
                        this._displayError(
                            _t("Server Error"),
                            _t("An error occurred when displaying this payment form."),
                            error.message.data.message
                        );
                    });
            },

            /**
             * Process payment by getting opaque data and creating profile.
             *
             * @override
             * @private
             * @param {String} code - The provider code
             * @param {Number} paymentOptionId - The payment option id
             * @param {String} flow - The payment flow
             * @returns {Promise}
             */
            _processPayment: function (code, paymentOptionId, flow) {
                if (code !== "authorize" || flow === "token") {
                    return this._super(...arguments);
                }

                // Check if this is the profile creation flow
                const profileRoute = this.$el.data("profile-creation-route");
                if (!profileRoute) {
                    // Not profile creation flow, use standard behavior
                    return this._super(...arguments);
                }

                if (!this._validateFormInputs(paymentOptionId)) {
                    this._enableButton();
                    $("body").unblock();
                    return Promise.resolve();
                }

                // Build authentication and card data for Accept.js
                const secureData = {
                    authData: {
                        apiLoginID: this.authorizeInfo.login_id,
                        clientKey: this.authorizeInfo.client_key,
                    },
                    ...this._getPaymentDetails(paymentOptionId),
                };

                // Dispatch to Accept.js to get opaque data
                return Accept.dispatchData(secureData, (response) =>
                    this._profileResponseHandler(paymentOptionId, response)
                );
            },

            /**
             * Handle Accept.js response and create the payment profile.
             *
             * @private
             * @param {Number} providerId - The selected provider id
             * @param {Object} response - The response from Accept.js
             * @returns {Promise}
             */
            _profileResponseHandler: function (providerId, response) {
                if (response.messages.resultCode === "Error") {
                    let error = "";
                    response.messages.message.forEach(
                        (msg) => (error += `${msg.code}: ${msg.text}\n`)
                    );
                    this._displayError(
                        _t("Payment Error"),
                        _t("We were not able to process your card."),
                        error
                    );
                    return Promise.resolve();
                }

                const profileRoute = this.$el.data("profile-creation-route");
                const partnerId = this.$el.data("partner-id");
                const accessToken = this.$el.data("access-token");
                const landingRoute = this.$el.data("landing-route");

                // Create the payment profile via our custom endpoint
                return this._rpc({
                    route: profileRoute,
                    params: {
                        provider_id: providerId,
                        partner_id: partnerId,
                        opaque_data: response.opaqueData,
                        access_token: accessToken,
                    },
                })
                    .then((result) => {
                        if (result.success) {
                            // Success - redirect to landing page
                            this._displayInfo(
                                _t("Success"),
                                _t("Payment method added successfully.")
                            );
                            window.location = landingRoute;
                        } else {
                            // Error from our endpoint
                            this._displayError(
                                _t("Payment Error"),
                                _t("Failed to save payment method."),
                                result.error || _t("Unknown error occurred.")
                            );
                        }
                    })
                    .guardedCatch((error) => {
                        error.event.preventDefault();
                        this._displayError(
                            _t("Server Error"),
                            _t("We were not able to save your payment method."),
                            error.message.data.message
                        );
                    });
            },

            /**
             * Display an info message.
             *
             * @private
             * @param {String} title - The message title
             * @param {String} description - The message description
             */
            _displayInfo: function (title, description) {
                // Simple info display - can be enhanced with proper UI
                console.info(`${title}: ${description}`);
            },

            /**
             * Validate that all form inputs meet their constraints.
             *
             * @private
             * @param {Number} providerId - The selected provider id
             * @returns {Boolean} - Whether all inputs are valid
             */
            _validateFormInputs: function (providerId) {
                const inputs = Object.values(this._getInlineFormInputs(providerId));
                return inputs.every((element) => element && element.reportValidity());
            },
        };

        manageForm.include(authorizeProfileMixin);
    }
);
