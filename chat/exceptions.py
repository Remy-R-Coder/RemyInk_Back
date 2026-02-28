from rest_framework.exceptions import APIException
from rest_framework import status


class ThreadNotFoundException(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Chat thread not found.'
    default_code = 'thread_not_found'


class UnauthorizedThreadAccessException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'You do not have permission to access this thread.'
    default_code = 'unauthorized_thread_access'


class InvalidSessionKeyException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid session key provided.'
    default_code = 'invalid_session_key'


class RateLimitExceededException(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = 'Rate limit exceeded. Please try again later.'
    default_code = 'rate_limit_exceeded'


class InvalidMessageException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid message content.'
    default_code = 'invalid_message'


class InvalidOfferException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid offer data.'
    default_code = 'invalid_offer'


class FileUploadException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'File upload failed.'
    default_code = 'file_upload_error'


class AttachmentNotFoundException(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Attachment not found.'
    default_code = 'attachment_not_found'


class MessageNotFoundException(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Message not found.'
    default_code = 'message_not_found'


class FreelancerOnlyException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'Only freelancers can perform this action.'
    default_code = 'freelancer_only'


class ClientOnlyException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'Only clients can perform this action.'
    default_code = 'client_only'