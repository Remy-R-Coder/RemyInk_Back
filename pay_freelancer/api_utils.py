import requests
import json
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import logging

logger = logging.getLogger(__name__)

def get_paystack_headers():
    if not settings.PAYSTACK_SECRET_KEY:
        raise ImproperlyConfigured("PAYSTACK_SECRET_KEY is not set.")
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

def initiate_transfer(recipient_code, amount_ngn, reference=None):
    url = "https://api.paystack.co/transfer"
    
    amount_kobo = int(float(amount_ngn) * 100)
    
    payload = {
        "source": "balance",
        "reason": "Freelancer Payout",
        "amount": amount_kobo,
        "recipient": recipient_code,
        "reference": reference
    }

    try:
        response = requests.post(url, headers=get_paystack_headers(), data=json.dumps(payload))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error initiating transfer: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error initiating Paystack transfer: {e}")
        return {"status": False, "message": str(e)}

def verify_transfer(transfer_code):
    url = f"https://api.paystack.co/transfer/verify/{transfer_code}"
    
    try:
        response = requests.get(url, headers=get_paystack_headers())
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error verifying transfer: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error verifying Paystack transfer: {e}")
        return {"status": False, "message": str(e)}

def get_transfer_status(transfer_code):
    url = f"https://api.paystack.co/transfer/{transfer_code}"
    
    try:
        response = requests.get(url, headers=get_paystack_headers())
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error getting transfer status: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error getting Paystack transfer status: {e}")
        return {"status": False, "message": str(e)}

def list_transfers(per_page=50, page=1, status=None):
    url = "https://api.paystack.co/transfer"
    params = {
        "perPage": per_page,
        "page": page
    }
    
    if status:
        params["status"] = status
    
    try:
        response = requests.get(url, headers=get_paystack_headers(), params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error listing transfers: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error listing Paystack transfers: {e}")
        return {"status": False, "message": str(e)}

def get_balance():
    url = "https://api.paystack.co/balance"
    
    try:
        response = requests.get(url, headers=get_paystack_headers())
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error getting balance: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error getting Paystack balance: {e}")
        return {"status": False, "message": str(e)}

def create_transfer_recipient(name, account_number, bank_code, type="nuban"):
    url = "https://api.paystack.co/transferrecipient"
    
    payload = {
        "type": type,
        "name": name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": "NGN"
    }
    
    try:
        response = requests.post(url, headers=get_paystack_headers(), data=json.dumps(payload))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error creating recipient: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error creating Paystack recipient: {e}")
        return {"status": False, "message": str(e)}

def finalize_transfer(transfer_code, otp):
    url = f"https://api.paystack.co/transfer/finalize_transfer"
    
    payload = {
        "transfer_code": transfer_code,
        "otp": otp
    }
    
    try:
        response = requests.post(url, headers=get_paystack_headers(), data=json.dumps(payload))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Paystack HTTP Error finalizing transfer: {e.response.text}")
        return e.response.json()
    except Exception as e:
        logger.error(f"Error finalizing Paystack transfer: {e}")
        return {"status": False, "message": str(e)}

def process_payout(payout, user=None):
    from pay_freelancer.models import PayoutStatus
    
    try:
        if payout.status != PayoutStatus.PENDING:
            raise ValueError(f"Cannot process payout with status: {payout.status}")
        
        if not payout.recipient_code:
            raise ValueError("Recipient code is required")
        
        if payout.payout_amount < payout.MINIMUM_PAYOUT:
            raise ValueError(f"Payout amount {payout.payout_amount} is below minimum {payout.MINIMUM_PAYOUT}")
        
        if payout.freelancer.current_balance < payout.payout_amount:
            raise ValueError(f"Insufficient balance. Available: {payout.freelancer.current_balance}, Required: {payout.payout_amount}")
        
        response = initiate_transfer(
            recipient_code=payout.recipient_code,
            amount_ngn=float(payout.payout_amount),
            reference=payout.reference
        )
        
        if response.get("status"):
            data = response.get("data", {})
            transfer_code = data.get("transfer_code")
            
            payout.mark_as_initiated(transfer_code=transfer_code, user=user)
            payout.response_data = response
            
            logger.info(f"Payout {payout.reference} initiated with transfer code: {transfer_code}")
            return True, response
        else:
            error_message = response.get("message", "Unknown error")
            payout.mark_as_failed(error_message=error_message, response_data=response, user=user)
            logger.error(f"Failed to initiate payout {payout.reference}: {error_message}")
            return False, response
            
    except Exception as e:
        error_message = str(e)
        payout.mark_as_failed(error_message=error_message, user=user)
        logger.error(f"Error processing payout {payout.reference}: {error_message}")
        return False, {"status": False, "message": error_message}

def check_and_update_payout_status(payout):
    from pay_freelancer.models import PayoutStatus
    
    try:
        if not payout.transfer_code:
            return False, {"status": False, "message": "No transfer code associated with payout"}
        
        if payout.status not in [PayoutStatus.INITIATED, PayoutStatus.PENDING]:
            return False, {"status": False, "message": f"Cannot check status for payout with status: {payout.status}"}
        
        response = get_transfer_status(payout.transfer_code)
        
        if response.get("status"):
            data = response.get("data", {})
            status = data.get("status")
            
            if status == "success":
                payout.mark_as_success(response_data=response)
                return True, response
            elif status == "failed":
                error_message = data.get("failure_reason", "Transfer failed")
                payout.mark_as_failed(error_message=error_message, response_data=response)
                return False, response
            elif status in ["pending", "otp"]:
                payout.response_data = response
                payout.save(update_fields=['response_data'])
                return True, response
            else:
                payout.response_data = response
                payout.save(update_fields=['response_data'])
                return True, response
        else:
            error_message = response.get("message", "Unknown error")
            payout.mark_as_failed(error_message=error_message, response_data=response)
            return False, response
            
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error checking payout status {payout.reference}: {error_message}")
        return False, {"status": False, "message": error_message}

def retry_failed_payout(payout, user=None):
    from pay_freelancer.models import PayoutStatus
    
    try:
        if not payout.can_retry():
            return False, {"status": False, "message": "Payout cannot be retried"}
        
        if not payout.recipient_code:
            return False, {"status": False, "message": "Recipient code is required"}
        
        payout.increment_retry_count()
        payout.status = PayoutStatus.PENDING
        payout.save(update_fields=['status', 'retry_count', 'last_retry_at'])
        
        payout.log_status_update(f"Retry #{payout.retry_count} initiated", user=user)
        
        success, response = process_payout(payout, user)
        return success, response
        
    except Exception as e:
        error_message = str(e)
        payout.mark_as_failed(error_message=error_message, user=user)
        logger.error(f"Error retrying payout {payout.reference}: {error_message}")
        return False, {"status": False, "message": error_message}

def batch_process_payouts(payouts, user=None):
    results = {
        "total": len(payouts),
        "successful": 0,
        "failed": 0,
        "details": []
    }
    
    for payout in payouts:
        try:
            success, response = process_payout(payout, user)
            if success:
                results["successful"] += 1
                results["details"].append({
                    "payout": payout.reference,
                    "status": "success",
                    "transfer_code": payout.transfer_code
                })
            else:
                results["failed"] += 1
                results["details"].append({
                    "payout": payout.reference,
                    "status": "failed",
                    "error": response.get("message", "Unknown error")
                })
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "payout": payout.reference,
                "status": "error",
                "error": str(e)
            })
    
    return results

def get_payout_fee_amount(payout_amount, percentage_fee=Decimal('1.5')):
    fee = (payout_amount * percentage_fee) / Decimal('100')
    return fee.quantize(Decimal('0.01'))