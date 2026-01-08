"""AI-powered URL selector using GPT-4o-mini"""
import os
import json
import logging
from typing import List, Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

class AIURLSelector:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize AI URL Selector with OpenAI API key"""
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o-mini"
    
    def select_best_url(
        self,
        store_name: str,
        country: Optional[str] = None,
        review_text: Optional[str] = None,
        search_results: List[Dict] = None
    ) -> Dict:
        """
        Use AI to select the best matching URL from search results
        
        Args:
            store_name: Name of the store to find
            country: Country of the store (optional)
            review_text: Review text context (optional)
            search_results: List of search result dictionaries with keys:
                - url: str
                - title: str
                - snippet: str
                - is_shopify: bool
                - relevance_score: int
        
        Returns:
            Dict with:
                - selected_url: str (URL of best match)
                - confidence: float (0.0-1.0)
                - reasoning: str (explanation)
                - selected_index: int (index in original results)
        """
        if not search_results or len(search_results) == 0:
            return {
                'selected_url': None,
                'confidence': 0.0,
                'reasoning': 'No search results provided',
                'selected_index': -1
            }
        
        try:
            # Format search results for prompt
            results_text = self._format_search_results(search_results)
            
            # Build context
            context_parts = [f"Store Name: {store_name}"]
            if country:
                context_parts.append(f"Country: {country}")
            if review_text:
                # Truncate review text to first 200 chars
                review_snippet = review_text[:200] + "..." if len(review_text) > 200 else review_text
                context_parts.append(f"Review Context: {review_snippet}")
            
            context = "\n".join(context_parts)
            
            # Create prompt
            prompt = f"""You are helping to find the correct Shopify store URL from Google search results.

Store Information:
{context}

Search Results:
{results_text}

Task: Analyze these search results and select the most likely correct Shopify store URL for "{store_name}".

Consider:
1. Store name matching (exact match is best, but also consider partial matches, abbreviations, and semantic similarity)
2. Country relevance (if country is provided)
3. Whether the URL is actually a Shopify store (look for .myshopify.com, Shopify mentions, or e-commerce indicators)
4. Whether it's a store page (not a review site, blog post, social media, or Wikipedia page)
5. Relevance score and position in results

Return ONLY a valid JSON object with this exact structure:
{{
    "selected_url": "the_best_matching_url",
    "confidence": 0.95,
    "reasoning": "Brief explanation of why this URL was selected",
    "selected_index": 0
}}

Important:
- selected_url must be one of the URLs from the search results above
- confidence should be between 0.0 and 1.0 (higher = more confident)
- selected_index should be the 0-based index of the selected URL in the results list
- If no good match exists, select the best available option and set confidence accordingly
- reasoning should be concise (1-2 sentences)"""
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at matching store names to their correct Shopify store URLs. Always respond with valid JSON only."
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
            
            # Validate result
            selected_url = result.get('selected_url')
            selected_index = result.get('selected_index', -1)
            
            # Verify the selected URL exists in search results
            if selected_index >= 0 and selected_index < len(search_results):
                actual_url = search_results[selected_index]['url']
                if selected_url != actual_url:
                    logger.warning(f"AI selected URL mismatch. Expected: {actual_url}, Got: {selected_url}")
                    # Use the URL from the index instead
                    selected_url = actual_url
            else:
                # Try to find URL in results
                found = False
                for idx, res in enumerate(search_results):
                    if res['url'] == selected_url:
                        selected_index = idx
                        found = True
                        break
                
                if not found:
                    logger.warning(f"Selected URL not found in results: {selected_url}")
                    # Fallback to first result
                    selected_index = 0
                    selected_url = search_results[0]['url']
                    result['confidence'] = 0.5
                    result['reasoning'] = "No clear match found, using first result"
            
            return {
                'selected_url': selected_url,
                'confidence': float(result.get('confidence', 0.5)),
                'reasoning': result.get('reasoning', 'No reasoning provided'),
                'selected_index': selected_index
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response was: {result_text}")
            # Fallback to first result
            return {
                'selected_url': search_results[0]['url'] if search_results else None,
                'confidence': 0.3,
                'reasoning': 'AI response parsing failed, using first result',
                'selected_index': 0
            }
        except Exception as e:
            logger.error(f"Error in AI URL selection: {e}", exc_info=True)
            # Fallback to first result
            return {
                'selected_url': search_results[0]['url'] if search_results else None,
                'confidence': 0.3,
                'reasoning': f'AI selection error: {str(e)}',
                'selected_index': 0
            }
    
    def _format_search_results(self, results: List[Dict]) -> str:
        """Format search results for the prompt"""
        formatted = []
        for idx, result in enumerate(results):
            shopify_badge = " [SHOPIFY STORE]" if result.get('is_shopify') else ""
            formatted.append(f"""
{idx}. URL: {result.get('url', 'N/A')}
   Title: {result.get('title', 'N/A')}{shopify_badge}
   Snippet: {result.get('snippet', 'N/A')[:150]}
   Relevance Score: {result.get('relevance_score', 0)}
""")
        return "\n".join(formatted)


