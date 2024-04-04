import wf_core_data
import gspread
import gspread_pandas
import datetime
import logging
import os

# Set up logger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get configuration from environment variables

TRANSPARENT_CLASSROOM_USERNAME = os.environ.get('TRANSPARENT_CLASSROOM_USERNAME')
TRANSPARENT_CLASSROOM_PASSWORD = os.environ.get('TRANSPARENT_CLASSROOM_PASSWORD')

RECIPIENT_EMAIL_ADDRESS = os.environ.get('TC_DOWNLOAD_RECIPIENT_EMAIL_ADDRESS')

SPREADSHEET_NAME_BASE = os.environ.get('TC_DOWNLOAD_SPREADSHEET_NAME_BASE', 'transparent_classroom_rosters')

SERVICE_ACCOUNT_INFO_DICT = {
    'type': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_TYPE', 'service_account'),
    'project_id': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_PROJECT_ID'),
    'private_key_id': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_PRIVATE_KEY_ID'),
    'private_key': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_PRIVATE_KEY'),
    'client_email': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_CLIENT_EMAIL'),
    'client_id': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_CLIENT_ID'),
    'auth_uri': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_AUTH_URI', 'https://accounts.google.com/o/oauth2/auth'),
    'token_uri': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_TOKEN_URI', 'https://oauth2.googleapis.com/token'),
    'auth_provider_x509_cert_url': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_AUTH_PROVIDER_X509_CERT_URL', 'https://www.googleapis.com/oauth2/v1/certs'),
    'client_x509_cert_url': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_CLIENT_X509_CERT_URL'),
    'universe_domain': os.environ.get('TC_DOWNLOAD_GOOGLE_AUTH_UNIVERSE_DOMAIN', 'googleapis.com'),
}

# Define handlers

def fetch_and_store_rosters_current(event, context):
    timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
    student_data_combined, teacher_data_combined = fetch_rosters(
        only_current=True,
        username=TRANSPARENT_CLASSROOM_USERNAME,
        password=TRANSPARENT_CLASSROOM_PASSWORD,
    )
    timestamp_string = timestamp.strftime('%Y%m%d_%H%M%S')
    spreadsheet_name = f'{SPREADSHEET_NAME_BASE}_current_{timestamp_string}'
    spreadsheet_id = store_rosters(
        student_data_combined=student_data_combined,
        teacher_data_combined=teacher_data_combined,
        spreadsheet_name=spreadsheet_name,
        recipient_email_address=RECIPIENT_EMAIL_ADDRESS,
        service_account_info_dict=SERVICE_ACCOUNT_INFO_DICT,
    )
    body = {
        "message": f"Success. Data stored in spreadsheet {spreadsheet_id}",
        "input": event,
    }

    response = {"statusCode": 200, "body": json.dumps(body)}
    return response

# Define helper functions

def fetch_rosters(
    only_current=False,
    username=None,
    password=None,
    api_token=None,
    url_base='https://www.transparentclassroom.com/api/v1/',
):
    tc_client = wf_core_data.TransparentClassroomClient(
        username=username,
        password=password,
        api_token=api_token,
        url_base=url_base,
    )
    school_data = tc_client.fetch_school_data(
        pull_datetime=None,
        format='dataframe'
    )
    school_ids = school_data.index.tolist()
    student_classroom_data = tc_client.fetch_student_classroom_data(
        school_ids=school_ids,
        session_data=None,
        pull_datetime=None,
        only_current=only_current,
        format='dataframe'
    )
    classroom_data = tc_client.fetch_classroom_data(
        school_ids=school_ids,
        pull_datetime=None,
        format='dataframe'
    )
    student_data, student_parent_data = tc_client.fetch_student_data(
        school_ids=school_ids,
        pull_datetime=None,
        only_current=only_current,
        format='dataframe'
    )
    teacher_data = tc_client.fetch_teacher_data(
        school_ids=school_ids,
        pull_datetime=None,
        format='dataframe'
    )
    student_data_combined = (
        student_classroom_data
        .droplevel('session_id_tc')
        .drop(columns='pull_datetime')
        .join(
            school_data['school_name_tc'],
            how='left',
            on='school_id_tc'
        )
        .join(
            classroom_data['classroom_name_tc'],
            how='left',
            on=['school_id_tc', 'classroom_id_tc']
        )
        .join(
            student_data.reindex(columns=[
                'student_first_name_tc',
                'student_middle_name_tc',
                'student_last_name_tc',
                'student_birth_date_tc',
                'student_gender_tc',
                'student_dominant_language_tc',
                'student_ethnicity_tc',
                'student_grade_tc',
                'student_first_day_tc',
                'student_last_day_tc',
                'student_id_alt_tc',
            ]),
            how='inner',
            on=['school_id_tc', 'student_id_tc']
        )
        .sort_values([
            'school_name_tc',
            'classroom_name_tc',
            'student_last_name_tc',
            'student_first_name_tc'
        ])
    )
    teacher_data_combined = (
        teacher_data
        .join(
            school_data['school_name_tc'],
            how='left',
            on='school_id_tc'
        )
        .reindex(columns=[
            'school_name_tc',
            'user_first_name_tc',
            'user_last_name_tc',
            'user_email_tc'
        ])
        .sort_values([
            'school_name_tc',
            'user_last_name_tc',
            'user_first_name_tc'
        ])
    )
    return student_data_combined, teacher_data_combined

def store_rosters(
    student_data_combined,
    teacher_data_combined,
    spreadsheet_name,
    recipient_email_address,
    service_account_info_dict,
):
    spreadsheet_id = create_google_sheet(
        spreadsheet_name=spreadsheet_name,
        service_account_info_dict=service_account_info_dict,
        recipient_email_address=recipient_email_address
    )
    credentials = gspread_pandas.conf.get_creds(
        config=service_account_info_dict
    )
    spread = gspread_pandas.Spread(
        spread=spreadsheet_id,
        creds=credentials
    )
    spread.df_to_sheet(
        df=student_data_combined,
        replace=True,
        sheet='Students'
    )
    spread.df_to_sheet(
        df=teacher_data_combined,
        replace=True,
        sheet='Teachers'
    )
    return spreadsheet_id

def create_google_sheet(
    spreadsheet_name,
    service_account_info_dict,
    recipient_email_address
):
    gspread_client = gspread.auth.service_account_from_dict(service_account_info_dict)
    sh = gspread_client.create(spreadsheet_name)
    sh.share(
        email_address=recipient_email_address,
        perm_type='user',
        role='writer',
        notify=True,
    )
    spreadsheet_id = sh.id
    return spreadsheet_id