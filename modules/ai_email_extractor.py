"""AI-powered email extractor using GPT to filter relevant emails"""
import os
import json
import logging
import re
from typing import List, Dict, Optional, Set
from openai import OpenAI

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

# Valid TLDs (common ones - this is not exhaustive but covers most cases)
VALID_TLDS = {
    'com', 'net', 'org', 'edu', 'gov', 'mil', 'int',
    'co', 'io', 'ai', 'app', 'dev', 'tech', 'online', 'store', 'shop',
    'us', 'uk', 'ca', 'au', 'de', 'fr', 'es', 'it', 'nl', 'be', 'ch', 'at',
    'jp', 'cn', 'in', 'br', 'mx', 'ar', 'za', 'ae', 'sa', 'sg', 'hk', 'nz',
    'se', 'no', 'dk', 'fi', 'pl', 'cz', 'ie', 'pt', 'gr', 'ro', 'hu',
    'info', 'biz', 'name', 'pro', 'xyz', 'website', 'site', 'email',
    'tv', 'cc', 'ws', 'me', 'mobi', 'tel', 'asia', 'jobs', 'travel',
    'dk', 'no', 'se', 'fi', 'is'  # Nordic countries
}

class AIEmailExtractor:
    """Use AI to extract only relevant emails related to a store URL"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize AI Email Extractor with OpenAI API key"""
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o-mini"
    
    def is_valid_email_format(self, email: str) -> bool:
        """
        Validate if email has a valid format with proper TLD
        
        Args:
            email: Email address to validate
            
        Returns:
            True if email format is valid
        """
        if not email or '@' not in email:
            return False
        
        try:
            local_part, domain = email.rsplit('@', 1)
            
            # Local part should not be empty
            if not local_part or len(local_part) > 64:
                return False
            
            # Domain should not be empty
            if not domain or len(domain) > 255:
                return False
            
            # Domain must have at least one dot
            domain_parts = domain.split('.')
            if len(domain_parts) < 2:
                return False
            
            # TLD validation
            tld = domain_parts[-1].lower()
            
            # TLD must be at least 2 characters
            if len(tld) < 2:
                return False
            
            # TLD must be alphabetic (no numbers)
            if not tld.isalpha():
                return False
            
            # Check if TLD is in valid list (or at least looks valid - 2-6 chars, all letters)
            if len(tld) > 6:
                return False  # TLDs are typically 2-6 characters
            
            # Reject version numbers (e.g., @0.1.99, @2.3.44)
            if any(part.isdigit() for part in domain_parts):
                # If any part is all digits, it's likely a version number
                if len(domain_parts) > 2 and any(len(part) <= 3 and part.isdigit() for part in domain_parts):
                    return False
            
            # Domain must contain at least one letter
            if not any(c.isalpha() for c in domain):
                return False
            
            # Reject common invalid patterns
            invalid_patterns = [
                '@localhost',
                '@127.',
                '@192.',
                '@10.',
            ]
            email_lower = email.lower()
            if any(pattern in email_lower for pattern in invalid_patterns):
                return False
            
            # Basic regex check
            if not EMAIL_RE.fullmatch(email):
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error validating email format {email}: {e}")
            return False
    
    def split_concatenated_emails(self, text: str) -> List[str]:
        """
        Attempt to split concatenated emails (e.g., "email1@domain.comemail2@domain.com")
        
        Args:
            text: Text that might contain concatenated emails
            
        Returns:
            List of potential email addresses
        """
        emails = []
        # Find all potential email patterns
        matches = list(EMAIL_RE.finditer(text))
        
        for match in matches:
            email = match.group(0)
            # Check if this email is valid
            if self.is_valid_email_format(email):
                emails.append(email)
        
        return emails
    
    def normalize_and_deduplicate_emails(self, raw_emails: List[str]) -> List[str]:
        """
        Normalize and deduplicate emails before sending to AI
        
        Args:
            raw_emails: List of raw email addresses
            
        Returns:
            List of normalized unique emails
        """
        normalized = {}
        seen_lower = set()
        
        for email in raw_emails:
            if not email:
                continue
            
            # Clean email: remove trailing dots, whitespace
            email = email.strip().rstrip('.').strip()
            
            # Check if email might be concatenated (contains multiple @ symbols or very long)
            if email.count('@') > 1 or len(email) > 100:
                # Try to split concatenated emails
                split_emails = self.split_concatenated_emails(email)
                for split_email in split_emails:
                    if self.is_valid_email_format(split_email):
                        email_lower = split_email.lower()
                        if email_lower not in seen_lower:
                            seen_lower.add(email_lower)
                            normalized[email_lower] = split_email
                continue
            
            # Validate email format
            if not self.is_valid_email_format(email):
                continue
            
            # Use lowercase for deduplication
            email_lower = email.lower()
            
            # Keep first occurrence (preserve original casing if possible)
            if email_lower not in seen_lower:
                seen_lower.add(email_lower)
                normalized[email_lower] = email
        
        return list(normalized.values())
    
    def extract_relevant_emails(
        self,
        raw_emails: List[str],
        store_url: str,
        store_name: Optional[str] = None
    ) -> Dict:
        """
        Extract only relevant emails using AI
        
        Args:
            raw_emails: List of all raw emails found during scraping
            store_url: Store URL for context
            store_name: Optional store name for context
            
        Returns:
            Dictionary with:
            {
                'emails': List[str],  # Filtered relevant emails
                'stats': {
                    'total_raw': int,
                    'total_relevant': int
                }
            }
        """
        if not raw_emails:
            logger.info("No raw emails to process")
            return {
                'emails': [],
                'stats': {
                    'total_raw': 0,
                    'total_relevant': 0
                }
            }
        
        try:
            # Pre-process: normalize and deduplicate emails
            normalized_emails = self.normalize_and_deduplicate_emails(raw_emails)
            logger.info(f"Normalized {len(raw_emails)} raw emails to {len(normalized_emails)} unique emails")
            
            if not normalized_emails:
                return {
                    'emails': [],
                    'stats': {
                        'total_raw': len(raw_emails),
                        'total_relevant': 0
                    }
                }
            
            # Extract domain from store URL for context
            from urllib.parse import urlparse
            parsed_url = urlparse(store_url if store_url.startswith(('http://', 'https://')) else f'https://{store_url}')
            store_domain = parsed_url.netloc.replace('www.', '').lower()
            
            # Build context
            context_parts = [f"Store URL: {store_url}"]
            if store_domain:
                context_parts.append(f"Store Domain: {store_domain}")
            if store_name:
                context_parts.append(f"Store Name: {store_name}")
            
            context = "\n".join(context_parts)
            
            # Create prompt with better guidance
            emails_list = "\n".join([f"- {email}" for email in normalized_emails])
            
            prompt = f"""You are filtering emails from a scraped list. You MUST ONLY return emails that are in the provided list below.

Context:
{context}

Emails found during scraping ({len(normalized_emails)} total) - YOU CAN ONLY RETURN EMAILS FROM THIS LIST:
{emails_list}

CRITICAL RULES:
1. **ONLY return emails from the list above** - DO NOT add, invent, or suggest any emails that are not in the provided list
2. **DO NOT add common email patterns** like info@, contact@, support@, sales@, hello@, help@, team@, office@, owner@, john@, jane@, etc. unless they are ACTUALLY in the list above
3. **Your job is to FILTER, not to ADD** - only exclude emails that are clearly invalid or spam

INCLUDE emails from the list that are:
- Valid email format (proper @domain.tld structure)
- Not obvious spam or test emails
- Not no-reply/noreply addresses
- Business-relevant (domain emails, third-party with business keywords, etc.)

EXCLUDE emails from the list that are:
- Invalid format (version numbers like @0.1.99, @2.3.44)
- Obvious spam (random long strings)
- Test/example emails (test@example.com, demo@test.com)
- No-reply/noreply (noreply@, no-reply@, donotreply@)
- Third-party emails that are clearly personal (random strings, unrelated names)

Return ONLY a valid JSON object with this exact structure:
{{
    "relevant_emails": ["email1@example.com", "email2@example.com"],
    "reasoning": "Brief explanation of why these emails were selected"
}}

CRITICAL: 
- Every email in "relevant_emails" MUST appear exactly in the list above (case-insensitive matching)
- DO NOT add any emails that are not in the provided list
- DO NOT suggest or invent common email patterns
- If an email is in the list and is valid, include it
- If an email is not in the list, DO NOT include it, even if it seems like it should exist"""
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are filtering emails from a provided list. You MUST ONLY return emails that are in the user's list. DO NOT add, invent, or suggest any emails. Your job is to FILTER the provided list, not to add new emails. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,  # Slightly higher for better understanding
                response_format={"type": "json_object"}  # Force JSON response
            )
            
            # Parse response
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            relevant_emails = result.get('relevant_emails', [])
            
            # Validate and filter returned emails
            valid_emails = []
            normalized_original = {email.lower(): email for email in normalized_emails}
            
            for email in relevant_emails:
                # First validate the email format
                if not self.is_valid_email_format(email):
                    logger.warning(f"AI returned invalid email format: {email}")
                    continue
                
                # STRICT: Only accept emails that are in the original list (case-insensitive)
                email_lower = email.lower()
                if email_lower in normalized_original:
                    # Use the original casing from normalized_emails
                    valid_emails.append(normalized_original[email_lower])
                else:
                    # REJECT any email not in the original list
                    logger.warning(f"AI returned email NOT in original list (REJECTED): {email}")
                    continue
            
            if len(valid_emails) != len(relevant_emails):
                logger.warning(f"AI returned {len(relevant_emails)} emails, {len(valid_emails)} passed validation")
            
            logger.info(f"AI extracted {len(valid_emails)} relevant emails from {len(normalized_emails)} normalized emails (from {len(raw_emails)} raw)")
            if result.get('reasoning'):
                logger.info(f"AI reasoning: {result.get('reasoning')}")
            
            return {
                'emails': valid_emails,
                'stats': {
                    'total_raw': len(raw_emails),
                    'total_relevant': len(valid_emails)
                }
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response was: {result_text}")
            # Fallback: return empty list
            return {
                'emails': [],
                'stats': {
                    'total_raw': len(raw_emails),
                    'total_relevant': 0
                }
            }
        except Exception as e:
            logger.error(f"Error in AI email extraction: {e}", exc_info=True)
            # Fallback: return empty list
            return {
                'emails': [],
                'stats': {
                    'total_raw': len(raw_emails),
                    'total_relevant': 0
                }
            }

