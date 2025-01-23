def get_scheduler_instance():
    import os
    from apscheduler.schedulers.background import BackgroundScheduler
    import pytz
    return BackgroundScheduler(
        timezone=pytz.UTC,
        job_defaults={
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 3600
        }
    )

def send_backup_email(app, recipient_email, db_path):
    import os
    import base64
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"Starting backup email to {recipient_email}")

    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    creds = None
    
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            logger.error("Invalid credentials")
            return
            
    service = build('gmail', 'v1', credentials=creds)
    
    message = MIMEMultipart()
    message['to'] = recipient_email
    message['from'] = recipient_email
    message['subject'] = "BD EDxo"
    
    text_part = MIMEText('Bonjour, voici la dernière version de la BD de EDxo', 'plain')
    message.attach(text_part)
    
    with open(db_path, 'rb') as f:
        file_data = f.read()
    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(file_data)
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment', filename='backup.db')
    message.attach(attachment)
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    try:
        sent_message = service.users().messages().send(
            userId='me', 
            body={'raw': raw}
        ).execute()
        logger.info(f"Message sent. ID: {sent_message['id']}")
    except Exception as e:
        logger.error(f"Error sending email: {e}", exc_info=True)