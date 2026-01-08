"""Email processing and filtering module"""
import re
import logging
from typing import List, Dict, Set, Optional, Tuple, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Common third-party email domains
THIRD_PARTY_DOMAINS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk', 'yahoo.fr',
    'outlook.com', 'hotmail.com', 'hotmail.co.uk', 'live.com', 'msn.com',
    'icloud.com', 'me.com', 'mac.com', 'aol.com', 'protonmail.com',
    'zoho.com', 'yandex.com', 'mail.com', 'gmx.com'
}

# Legitimate keywords for third-party emails
LEGITIMATE_THIRD_PARTY_PATTERNS = [
    'contact', 'info', 'hello', 'support', 'help', 'sales', 'business',
    'service', 'customerservice', 'team', 'inquiries', 'inquiry',
    'admin', 'office', 'general', 'mail', 'enquiries', 'enquiry',
    'customersupport', 'customer.service', 'customercare', 'care',
    'assistance', 'hello', 'hi', 'reach', 'getintouch', 'get-in-touch'
]

# Keywords that suggest spam/personal emails
SPAM_PATTERNS = [
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'no.reply',
    'test', 'example', 'demo', 'sample', 'spam', 'trash'
]

# Valid top-level domains (TLD) - common ones
VALID_TLDS = {
    'com', 'net', 'org', 'edu', 'gov', 'mil', 'int',
    'co', 'io', 'ai', 'app', 'dev', 'tech', 'online', 'store', 'shop',
    'us', 'uk', 'ca', 'au', 'de', 'fr', 'es', 'it', 'nl', 'be', 'ch', 'at',
    'jp', 'cn', 'in', 'br', 'mx', 'ar', 'za', 'ae', 'sa', 'sg', 'hk', 'nz',
    'se', 'no', 'dk', 'fi', 'pl', 'cz', 'ie', 'pt', 'gr', 'ro', 'hu',
    'info', 'biz', 'name', 'pro', 'xyz', 'website', 'site', 'email', 'email',
    'tv', 'cc', 'ws', 'me', 'mobi', 'tel', 'asia', 'jobs', 'travel'
}


class EmailProcessor:
    """Process and filter emails based on domain relevance"""
    
    def __init__(self, use_ai_validation: bool = False, ai_validator: Optional[Callable] = None):
        """
        Initialize email processor
        
        Args:
            use_ai_validation: Whether to use AI for ambiguous third-party emails
            ai_validator: Optional async AI validator function: async def(email, store_url, store_name) -> Dict
        """
        self.use_ai_validation = use_ai_validation
        self.ai_validator = ai_validator
    
    def is_valid_email_format(self, email: str) -> bool:
        """
        Validate if email has a valid format (not version numbers, IPs, etc.)
        
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
            
            # Domain should not be just numbers (e.g., "2.3.44")
            # Check if domain is mostly/all numbers with dots
            domain_parts = domain.split('.')
            if len(domain_parts) < 2:
                return False  # Must have at least one dot
            
            # Check if TLD is all numbers (invalid)
            tld = domain_parts[-1].lower()
            if tld.isdigit():
                return False  # TLD cannot be just numbers (e.g., "version@2.3.44")
            
            # Check if domain without TLD is all numbers
            domain_without_tld = '.'.join(domain_parts[:-1])
            if domain_without_tld.replace('.', '').isdigit() and len(domain_without_tld) > 3:
                return False  # Domain like "2.3" is likely a version number
            
            # Domain should contain at least one letter (not all numbers/dots)
            if not any(c.isalpha() for c in domain):
                return False  # Domain must contain at least one letter
            
            # TLD should be at least 2 characters and contain letters
            if len(tld) < 2 or not tld.isalpha():
                return False
            
            # Reject common invalid patterns
            invalid_patterns = [
                'version@',  # Version numbers
                '@localhost',  # Localhost
                '@127.',  # IP addresses
                '@192.',  # IP addresses
                '@10.',  # IP addresses
            ]
            email_lower = email.lower()
            if any(pattern in email_lower for pattern in invalid_patterns):
                return False
            
            # Basic regex check for valid characters
            import re
            email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$')
            if not email_pattern.match(email):
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error validating email format {email}: {e}")
            return False
    
    def normalize_email(self, email: str) -> str:
        """
        Normalize email for deduplication
        
        Args:
            email: Email address to normalize
            
        Returns:
            Normalized email address
        """
        if not email or '@' not in email:
            return email.lower().strip()
        
        email = email.lower().strip()
        local_part, domain = email.split('@', 1)
        
        # Handle Gmail/GoogleMail aliasing
        if domain in ['gmail.com', 'googlemail.com']:
            # Remove +tags (e.g., user+tag@gmail.com -> user@gmail.com)
            local_part = local_part.split('+')[0]
            # Gmail ignores dots, remove them for normalization
            local_part = local_part.replace('.', '')
            # Normalize googlemail.com to gmail.com
            domain = 'gmail.com'
        
        # Normalize other known aliases
        if domain == 'googlemail.com':
            domain = 'gmail.com'
        
        return f"{local_part}@{domain}"
    
    def deduplicate_emails(self, emails: List[str]) -> List[str]:
        """
        Remove duplicate emails while preserving original case for display
        
        Args:
            emails: List of email addresses
            
        Returns:
            List of unique email addresses (original case preserved)
        """
        seen = set()
        unique = []
        
        for email in emails:
            # First validate email format
            if not self.is_valid_email_format(email):
                logger.debug(f"Invalid email format rejected: {email}")
                continue
            
            normalized = self.normalize_email(email)
            if normalized not in seen:
                seen.add(normalized)
                unique.append(email)  # Keep original case for display
        
        return unique
    
    def extract_domain_from_url(self, url: str) -> str:
        """
        Extract root domain from URL
        
        Args:
            url: Store URL
            
        Returns:
            Root domain (without www.)
        """
        if not url:
            return ''
        
        # Ensure URL has protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www.
            domain = domain.replace('www.', '')
            
            # Handle Shopify myshopify.com stores
            # For now, keep as-is. Custom domain matching will be handled separately
            return domain
        except Exception as e:
            logger.error(f"Error extracting domain from URL {url}: {e}")
            return ''
    
    def is_domain_email(self, email: str, store_domain: str) -> bool:
        """
        Check if email belongs to store domain (exact match)
        
        Args:
            email: Email address to check
            store_domain: Store's domain
            
        Returns:
            True if email domain matches store domain
        """
        if not email or '@' not in email or not store_domain:
            return False
        
        email_domain = email.split('@', 1)[1].lower()
        store_domain_clean = store_domain.lower().replace('www.', '')
        
        # Direct match
        if email_domain == store_domain_clean:
            return True
        
        # Handle www. variations
        if email_domain == f"www.{store_domain_clean}" or email_domain == store_domain_clean.replace('www.', ''):
            return True
        
        return False
    
    def is_subdomain_email(self, email: str, store_domain: str) -> bool:
        """
        Check if email is from a subdomain of store domain
        
        Args:
            email: Email address to check
            store_domain: Store's root domain
            
        Returns:
            True if email is from a subdomain
        """
        if not email or '@' not in email or not store_domain:
            return False
        
        email_domain = email.split('@', 1)[1].lower()
        store_domain_clean = store_domain.lower().replace('www.', '')
        
        # Email domain ends with .store_domain (e.g., support.store.com)
        if email_domain.endswith('.' + store_domain_clean):
            return True
        
        return False
    
    def is_third_party_email(self, email: str) -> bool:
        """
        Check if email is from a third-party provider
        
        Args:
            email: Email address to check
            
        Returns:
            True if email is from third-party provider
        """
        if not email or '@' not in email:
            return False
        
        email_domain = email.split('@', 1)[1].lower()
        return email_domain in THIRD_PARTY_DOMAINS
    
    def is_legitimate_keyword_email(self, email: str) -> bool:
        """
        Check if third-party email contains legitimate business keywords
        
        Args:
            email: Email address to check
            
        Returns:
            True if email contains legitimate keywords
        """
        if not email or '@' not in email:
            return False
        
        local_part = email.split('@', 1)[0].lower()
        
        # Check for spam patterns first
        for spam_pattern in SPAM_PATTERNS:
            if spam_pattern in local_part:
                return False
        
        # Check for legitimate keywords
        for pattern in LEGITIMATE_THIRD_PARTY_PATTERNS:
            if pattern in local_part:
                return True
        
        # If it's a very simple, short email (e.g., storename@gmail.com), might be legitimate
        # But be conservative - only if it's reasonably short and alphanumeric
        clean_local = local_part.replace('.', '').replace('-', '').replace('_', '')
        if len(local_part) < 20 and clean_local.isalnum():
            return True
        
        return False
    
    def categorize_emails(
        self, 
        emails: List[str], 
        store_url: str,
        store_name: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        Categorize emails by relevance
        
        Args:
            emails: List of email addresses
            store_url: Store URL for domain matching
            store_name: Optional store name for context
            
        Returns:
            Dictionary with categorized emails:
            {
                'domain': List[str],           # Exact domain match
                'subdomain': List[str],        # Subdomain match
                'third_party_legitimate': List[str],  # Third-party with keywords
                'third_party_ambiguous': List[str],   # Third-party without keywords (needs AI)
                'other': List[str]             # Other domains
            }
        """
        store_domain = self.extract_domain_from_url(store_url)
        
        domain_emails = []
        subdomain_emails = []
        third_party_legitimate = []
        third_party_ambiguous = []
        other_emails = []
        
        for email in emails:
            # Validate email format first (filters out version@2.3.44, etc.)
            if not email or '@' not in email or not self.is_valid_email_format(email):
                continue
            
            email_domain = email.split('@', 1)[1].lower()
            
            # Check domain match
            if self.is_domain_email(email, store_domain):
                domain_emails.append(email)
            elif self.is_subdomain_email(email, store_domain):
                subdomain_emails.append(email)
            elif email_domain in THIRD_PARTY_DOMAINS:
                # Third-party email
                if self.is_legitimate_keyword_email(email):
                    third_party_legitimate.append(email)
                else:
                    third_party_ambiguous.append(email)
            else:
                # Other domain
                other_emails.append(email)
        
        return {
            'domain': domain_emails,
            'subdomain': subdomain_emails,
            'third_party_legitimate': third_party_legitimate,
            'third_party_ambiguous': third_party_ambiguous,
            'other': other_emails
        }
    
    async def validate_ambiguous_third_party_with_ai(
        self,
        email: str,
        store_url: str,
        store_name: Optional[str] = None
    ) -> Tuple[bool, float, str]:
        """
        Use AI to validate ambiguous third-party email
        
        Args:
            email: Email address to validate
            store_url: Store URL for context
            store_name: Store name for context
            
        Returns:
            Tuple of (is_legitimate, confidence, reasoning)
        """
        if not self.use_ai_validation or not self.ai_validator:
            # If AI validation not enabled, default to conservative (reject)
            return False, 0.3, "AI validation not enabled"
        
        try:
            result = await self.ai_validator(email, store_url, store_name)
            return (
                result.get('is_legitimate', False),
                result.get('confidence', 0.5),
                result.get('reasoning', 'No reasoning provided')
            )
        except Exception as e:
            logger.error(f"Error validating email {email} with AI: {e}")
            return False, 0.3, f"AI validation error: {str(e)}"
    
    async def process_emails(
        self,
        raw_emails: List[str],
        store_url: str,
        store_name: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Complete email processing pipeline
        
        Args:
            raw_emails: List of raw email addresses from scraper
            store_url: Store URL for domain matching
            store_name: Optional store name for context
            
        Returns:
            Dictionary with processed results:
            {
                'primary': List[str],          # Domain + subdomain + legitimate third-party
                'secondary': List[str],        # AI-validated ambiguous third-party
                'all_unique': List[str],       # All filtered emails (primary + secondary)
                'categorized': Dict,           # Full categorization
                'stats': {
                    'total_raw': int,
                    'total_unique': int,
                    'domain_count': int,
                    'subdomain_count': int,
                    'third_party_legitimate_count': int,
                    'third_party_ambiguous_count': int,
                    'ai_validated_count': int,
                    'final_count': int
                }
            }
        """
        # Step 1: Deduplicate
        unique_emails = self.deduplicate_emails(raw_emails)
        logger.info(f"After deduplication: {len(unique_emails)} unique emails from {len(raw_emails)} raw emails")
        
        # Step 2: Categorize
        categorized = self.categorize_emails(unique_emails, store_url, store_name)
        
        # Step 3: Build primary list (domain + subdomain + legitimate third-party)
        primary_emails = (
            categorized['domain'] + 
            categorized['subdomain'] + 
            categorized['third_party_legitimate']
        )
        
        # Step 4: Handle ambiguous third-party emails
        secondary_emails = []
        ai_validated_count = 0
        
        if categorized['third_party_ambiguous'] and self.use_ai_validation:
            logger.info(f"Validating {len(categorized['third_party_ambiguous'])} ambiguous third-party emails with AI...")
            for email in categorized['third_party_ambiguous']:
                is_legitimate, confidence, reasoning = await self.validate_ambiguous_third_party_with_ai(
                    email, store_url, store_name
                )
                if is_legitimate and confidence >= 0.7:
                    secondary_emails.append(email)
                    ai_validated_count += 1
                    logger.info(f"AI validated {email} (confidence: {confidence:.2f}): {reasoning}")
        elif categorized['third_party_ambiguous']:
            # Without AI, we skip ambiguous third-party emails (conservative approach)
            logger.info(f"Skipping {len(categorized['third_party_ambiguous'])} ambiguous third-party emails (AI validation disabled)")
        
        # Step 5: Final results
        all_unique = primary_emails + secondary_emails
        
        stats = {
            'total_raw': len(raw_emails),
            'total_unique': len(unique_emails),
            'domain_count': len(categorized['domain']),
            'subdomain_count': len(categorized['subdomain']),
            'third_party_legitimate_count': len(categorized['third_party_legitimate']),
            'third_party_ambiguous_count': len(categorized['third_party_ambiguous']),
            'ai_validated_count': ai_validated_count,
            'final_count': len(all_unique)
        }
        
        logger.info(f"Email processing complete. Final: {stats['final_count']} emails")
        logger.info(f"  - Domain emails: {stats['domain_count']}")
        logger.info(f"  - Subdomain emails: {stats['subdomain_count']}")
        logger.info(f"  - Legitimate third-party: {stats['third_party_legitimate_count']}")
        logger.info(f"  - AI-validated third-party: {stats['ai_validated_count']}")
        
        return {
            'primary': primary_emails,
            'secondary': secondary_emails,
            'all_unique': all_unique,
            'categorized': categorized,
            'stats': stats
        }

