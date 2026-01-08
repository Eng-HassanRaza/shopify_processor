"""AI-powered email validator for third-party emails"""
import os
import json
import logging
from typing import Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

class AIEmailValidator:
    """Use AI to validate if a third-party email is legitimate business contact"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize AI Email Validator with OpenAI API key"""
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o-mini"
    
    def validate_email(
        self,
        email: str,
        store_url: str,
        store_name: Optional[str] = None
    ) -> Dict:
        """
        Synchronous email validation using OpenAI API
        (This will be wrapped in async executor when called from async context)
        """
        """
        Validate if a third-party email is likely a legitimate business contact
        
        Args:
            email: Email address to validate
            store_url: Store URL for context
            store_name: Optional store name for context
            
        Returns:
            Dictionary with:
            {
                'is_legitimate': bool,
                'confidence': float (0.0-1.0),
                'reasoning': str
            }
        """
        try:
            # Build context
            context_parts = [f"Store URL: {store_url}"]
            if store_name:
                context_parts.append(f"Store Name: {store_name}")
            
            context = "\n".join(context_parts)
            
            # Create prompt
            prompt = f"""You are helping to validate if a third-party email address (Gmail, Yahoo, Outlook, etc.) is likely a legitimate business contact email for a Shopify store.

Context:
{context}

Email to validate: {email}

Task: Analyze if this email is likely:
1. A legitimate business contact email (owner/team uses personal email for business)
2. A spam or personal email (not related to the business)

Consider:
- Email patterns (e.g., contact@gmail.com, storename@gmail.com are more likely legitimate)
- Email complexity (very long random emails are less likely)
- Common business email prefixes (contact, info, support, etc.)
- Store name similarity (if email contains store name, more likely legitimate)

Return ONLY a valid JSON object with this exact structure:
{{
    "is_legitimate": true/false,
    "confidence": 0.85,
    "reasoning": "Brief explanation (1-2 sentences)"
}}

Important:
- confidence should be between 0.0 and 1.0 (higher = more confident)
- reasoning should be concise
- Be conservative: if unsure, set is_legitimate to false"""
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at identifying legitimate business contact emails. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low temperature for consistency
                response_format={"type": "json_object"}  # Force JSON response
            )
            
            # Parse response
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            return {
                'is_legitimate': bool(result.get('is_legitimate', False)),
                'confidence': float(result.get('confidence', 0.5)),
                'reasoning': result.get('reasoning', 'No reasoning provided')
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response was: {result_text}")
            return {
                'is_legitimate': False,
                'confidence': 0.3,
                'reasoning': 'AI response parsing failed'
            }
        except Exception as e:
            logger.error(f"Error in AI email validation: {e}", exc_info=True)
            return {
                'is_legitimate': False,
                'confidence': 0.3,
                'reasoning': f'AI validation error: {str(e)}'
            }

