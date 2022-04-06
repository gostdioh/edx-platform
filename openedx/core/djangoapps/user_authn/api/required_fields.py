"""
Optional Fields API used by Authn MFE to populate progressive profiling form
"""

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.user_authn.api import form_fields
from openedx.core.djangoapps.user_authn.api.helper import RegistrationFieldsView
from openedx.core.djangoapps.user_authn.views.registration_form import get_registration_extension_form
from openedx.core.lib.api.authentication import BearerAuthentication


class RequiredFieldsView(RegistrationFieldsView):
    """
    Construct Registration forms and associated fields.
    """
    FIELD_TYPE = 'required'

    authentication_classes = (JwtAuthentication, BearerAuthentication, SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):  # lint-amnesty, pylint: disable=unused-argument
        """
        Returns the required fields configured in REGISTRATION_EXTRA_FIELDS settings.
        """
        # Custom form fields can be added via the form set in settings.REGISTRATION_EXTENSION_FORM
        custom_form = get_registration_extension_form() or {}
        response = {}
        for field in self.valid_fields:
            if custom_form and field in custom_form.fields:
                response[field] = form_fields.add_extension_form_field(
                    field, custom_form, custom_form.fields[field], self.FIELD_TYPE
                )
            else:
                field_handler = getattr(form_fields, f'add_{field}_field', None)
                if field_handler:
                    if field == 'honor_code':
                        terms_of_services = self._fields_setting.get("terms_of_service")
                        response[field] = field_handler(terms_of_services)
                    else:
                        response[field] = field_handler()

        if not self.valid_fields or not response:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={'error_code': 'required_fields_configured_incorrectly'}
            )

        return Response(
            status=status.HTTP_200_OK,
            data={
                'fields': response,
                'extended_profile': configuration_helpers.get_value('extended_profile_fields', []),
            },
        )
