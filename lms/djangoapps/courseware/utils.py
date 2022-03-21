"""Utility functions that have to do with the courseware."""


import datetime
import hashlib
from urllib import parse

from django.conf import settings
from edx_rest_api_client.client import OAuthAPIClient
from oauth2_provider.models import Application
from pytz import utc  # lint-amnesty, pylint: disable=wrong-import-order
from rest_framework import status
from xmodule.partitions.partitions import \
    ENROLLMENT_TRACK_PARTITION_ID  # lint-amnesty, pylint: disable=wrong-import-order
from xmodule.partitions.partitions_service import PartitionService  # lint-amnesty, pylint: disable=wrong-import-order

from common.djangoapps.course_modes.models import CourseMode
from lms.djangoapps.commerce.utils import EcommerceService
from lms.djangoapps.courseware.models import FinancialAssistanceConfiguration


def verified_upgrade_deadline_link(user, course=None, course_id=None):
    """
    Format the correct verified upgrade link for the specified ``user``
    in a course.

    One of ``course`` or ``course_id`` must be supplied. If both are specified,
    ``course`` will take priority.

    Arguments:
        user (:class:`~django.contrib.auth.models.User`): The user to display
            the link for.
        course (:class:`.CourseOverview`): The course to render a link for.
        course_id (:class:`.CourseKey`): The course_id of the course to render for.

    Returns:
        The formatted link that will allow the user to upgrade to verified
        in this course.
    """
    if course is not None:
        course_id = course.id
    return EcommerceService().upgrade_url(user, course_id)


def is_mode_upsellable(user, enrollment, course=None):
    """
    Return whether the user is enrolled in a mode that can be upselled to another mode,
    usually audit upselled to verified.
    The partition code allows this function to more accurately return results for masquerading users.

    Arguments:
        user (:class:`.AuthUser`): The user from the request.user property
        enrollment (:class:`.CourseEnrollment`): The enrollment under consideration.
        course (:class:`.ModulestoreCourse`): Optional passed in modulestore course.
            If provided, it is expected to correspond to `enrollment.course.id`.
            If not provided, the course will be loaded from the modulestore.
            We use the course to retrieve user partitions when calculating whether
            the upgrade link will be shown.
    """
    partition_service = PartitionService(enrollment.course.id, course=course)
    enrollment_track_partition = partition_service.get_user_partition(ENROLLMENT_TRACK_PARTITION_ID)
    group = partition_service.get_group(user, enrollment_track_partition)
    current_mode = None
    if group:
        try:
            current_mode = [
                mode.get('slug') for mode in settings.COURSE_ENROLLMENT_MODES.values() if mode['id'] == group.id
            ].pop()
        except IndexError:
            pass
    upsellable_mode = not current_mode or current_mode in CourseMode.UPSELL_TO_VERIFIED_MODES
    return upsellable_mode


def can_show_verified_upgrade(user, enrollment, course=None):
    """
    Return whether this user can be shown upgrade message.

    Arguments:
        user (:class:`.AuthUser`): The user from the request.user property
        enrollment (:class:`.CourseEnrollment`): The enrollment under consideration.
            If None, then the enrollment is not considered to be upgradeable.
        course (:class:`.ModulestoreCourse`): Optional passed in modulestore course.
            If provided, it is expected to correspond to `enrollment.course.id`.
            If not provided, the course will be loaded from the modulestore.
            We use the course to retrieve user partitions when calculating whether
            the upgrade link will be shown.
    """
    if enrollment is None:
        return False  # this got accidentally flipped in 2017 (commit 8468357), but leaving alone to not switch again

    if not is_mode_upsellable(user, enrollment, course):
        return False

    upgrade_deadline = enrollment.upgrade_deadline

    if upgrade_deadline is None:
        return False

    if datetime.datetime.now(utc).date() > upgrade_deadline.date():
        return False

    # Show the summary if user enrollment is in which allow user to upsell
    return enrollment.is_active and enrollment.mode in CourseMode.UPSELL_TO_VERIFIED_MODES


def is_eligible_for_financial_aid(course_id):
    """
    Sends a get request to edx-financial-assistance to retrieve financial assistance eligibility criteria for a course.

    Returns either True if course is eligible for financial aid and vice versa.
    Also returns the reason why the course isn't eligible.
    In case of a bad request, returns an error message.
    """
    is_eligible_url = '/core/api/course_eligibility/'
    financial_assistance_configuration = FinancialAssistanceConfiguration.current()
    if financial_assistance_configuration.enabled:
        oauth_application = Application.objects.get(user=financial_assistance_configuration.get_service_user())
        client = OAuthAPIClient(
            settings.LMS_ROOT_URL,
            oauth_application.client_id,
            oauth_application.client_secret
        )
        response = client.request('GET', f"{financial_assistance_configuration.api_url}{is_eligible_url}{course_id}/")
        if response.status_code == status.HTTP_200_OK:
            return response.json().get('is_eligible'), response.json().get('reason')
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            return False, response.json().get('message')
    else:
        return False, 'Financial Assistance configuration is not enabled'


def get_financial_assistance_application_status(user_id, course_id):
    """
    Given the course_id, sends a get request to edx-financial-assistance to retrieve
    financial assistance application status for the logged-in user.
    """
    application_status_url = f"/core/api/financial_assistance_application/status/?" \
                             f"{parse.urlencode({'course_id': course_id})}&{parse.urlencode({'lms_user_id': user_id})}"
    financial_assistance_configuration = FinancialAssistanceConfiguration.current()
    if financial_assistance_configuration.enabled:
        oauth_application = Application.objects.get(user=financial_assistance_configuration.get_service_user())
        client = OAuthAPIClient(
            settings.LMS_ROOT_URL,
            oauth_application.client_id,
            oauth_application.client_secret
        )
        response = client.request('GET', f"{financial_assistance_configuration.api_url}{application_status_url}")
        if response.status_code == status.HTTP_200_OK:
            return True, response.json()
        elif response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
            return False, response.json().get('message')

    else:
        return False, 'Financial Assistance configuration is not enabled'


def create_financial_assistance_application(form_data):
    """
    Sends a post request to edx-financial-assistance to create a new application for financial assistance application.
    The incoming form_data must have data as given in the example below:
    {
        "lms_user_id": <user_id>,
        "course_id": <course_run_id>,
        "income": <income_from_range>,
        "learner_reasons": <TEST_LONG_STRING>,
        "learner_goals": <TEST_LONG_STRING>,
        "learner_plans": <TEST_LONG_STRING>
    }
    """
    create_application_url = '/core/api/financial_assistance_applications'
    financial_assistance_configuration = FinancialAssistanceConfiguration.current()
    if financial_assistance_configuration.enabled:
        oauth_application = Application.objects.get(user=financial_assistance_configuration.get_service_user())
        client = OAuthAPIClient(
            settings.LMS_ROOT_URL,
            oauth_application.client_id,
            oauth_application.client_secret
        )
        response = client.request(
            'POST', f"{financial_assistance_configuration.api_url}{create_application_url}/", data=form_data
        )
        if response.status_code == status.HTTP_200_OK:
            return True, None
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            return False, response.json().get('message')
    return False, 'Financial Assistance configuration is not enabled'


def get_course_hash_value(course_key):
    """
    Returns a hash value for the given course key.
    If course key is None, function returns an out of bound value which will
    never satisfy the fa_backend_enabled_courses_percentage condition
    """
    out_of_bound_value = 100
    if course_key:
        m = hashlib.md5(str(course_key).encode())
        return int(m.hexdigest(), base=16) % 100

    return out_of_bound_value
