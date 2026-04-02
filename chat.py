import json
from google import genai
from google.genai import types
import warnings
from prompt import keys_and_prompt_setup, client_setup, Spinner, chat_client_setup

# Suppress the specific thought_signature warning from the SDK
warnings.filterwarnings("ignore", message=".*thought_signature.*")

# ═══════════════════════════════════════════════════════════════════════════
# Constants & Configuration
# ═══════════════════════════════════════════════════════════════════════════

# Gemini 2.5 Flash context window limits
MODEL = "gemini-2.5-flash"
CONTEXT_WINDOW_TOKENS = 1_000_000  # 1M tokens for flash model
SAFETY_THRESHOLD = 0.85  # Block at 85% of context window
ESTIMATED_TOKENS_PER_CHAR = 0.25  # Conservative estimate: 1 token ≈ 4 characters

# Load API keys and system instruction
with open('keys.json', 'r') as file:
    keys = json.load(file)
print('✓ API keys loaded successfully.')

keys, system_instruction = keys_and_prompt_setup(prompt_path='prompts/guardrail.txt')
print('✓ System instruction loaded successfully.')

client, _ = chat_client_setup(keys)

# Create config without thinking (gemini-2.5-flash doesn't support it)
scraper_client = types.Tool(google_search=types.GoogleSearch())
chat_config = types.GenerateContentConfig(tools=[scraper_client])
print('✓ Gemini client and config set up successfully.')

# ═══════════════════════════════════════════════════════════════════════════
# ChatSession Class - Encapsulates stateful chat with context management
# ═══════════════════════════════════════════════════════════════════════════

class ChatSession:
    """
    Managed chat session using Gemini SDK's native client.chats.create().
    Handles context window management, token counting, and graceful blocking.
    """
    
    def __init__(self, system_prompt=None):
        """Initialize a new chat session with optional system prompt."""
        self.system_prompt = system_prompt or system_instruction
        
        # Create native Gemini chat session
        self.chat_session = client.chats.create(
            model=MODEL,
            config=chat_config
        )
        
        # Track token usage (estimated)
        self.estimated_tokens_used = self._estimate_tokens(self.system_prompt)
        self.max_tokens_available = CONTEXT_WINDOW_TOKENS
        
        # Send system instruction to establish context
        try:
            self.chat_session.send_message(self.system_prompt)
            print("✓ System instruction established in chat session")
        except Exception as e:
            print(f"⚠ Warning: Could not establish system instruction: {e}")
    
    def _estimate_tokens(self, text):
        """Estimate token count from text (conservative: 1 token ≈ 4 chars)."""
        if not text:
            return 0
        return max(1, int(len(text) * ESTIMATED_TOKENS_PER_CHAR))
    
    def _get_context_usage_percent(self):
        """Get current context window usage as percentage."""
        if self.max_tokens_available <= 0:
            return 100.0
        return (self.estimated_tokens_used / self.max_tokens_available) * 100
    
    def _is_context_full(self):
        """Check if context window usage exceeds safety threshold."""
        return self._get_context_usage_percent() >= (SAFETY_THRESHOLD * 100)
    
    def send_message(self, user_message):
        """
        Send a message to the chat session with context checks.
        
        Args:
            user_message: The user's input message
            
        Returns:
            dict: {
                'success': bool,
                'response': str (or None if blocked),
                'tokens_used': int,
                'tokens_available': int,
                'context_usage_percent': float,
                'blocked': bool,
                'reason': str (if blocked)
            }
        """
        
        # Check context window before sending
        usage_percent = self._get_context_usage_percent()
        
        if self._is_context_full():
            return {
                'success': False,
                'response': None,
                'tokens_used': self.estimated_tokens_used,
                'tokens_available': self.max_tokens_available,
                'context_usage_percent': usage_percent,
                'blocked': True,
                'reason': f'Context window at {usage_percent:.1f}% - approaching limit'
            }
        
        # Estimate tokens for this message
        message_tokens = self._estimate_tokens(user_message)
        
        # Check if single message would exceed limit
        if self.estimated_tokens_used + message_tokens > CONTEXT_WINDOW_TOKENS:
            return {
                'success': False,
                'response': None,
                'tokens_used': self.estimated_tokens_used,
                'tokens_available': self.max_tokens_available,
                'context_usage_percent': usage_percent,
                'blocked': True,
                'reason': f'Message too long ({message_tokens} tokens) for remaining context'
            }
        
        spinner = Spinner("Gemini is thinking")
        spinner.start()
        
        try:
            # Send message using native chat session
            response = self.chat_session.send_message(user_message)
            response_text = response.text
            
            # Update token tracking
            self.estimated_tokens_used += message_tokens
            response_tokens = self._estimate_tokens(response_text)
            self.estimated_tokens_used += response_tokens
            
            return {
                'success': True,
                'response': response_text,
                'tokens_used': self.estimated_tokens_used,
                'tokens_available': self.max_tokens_available,
                'context_usage_percent': self._get_context_usage_percent(),
                'blocked': False,
                'reason': None
            }
            
        except Exception as e:
            return {
                'success': False,
                'response': None,
                'tokens_used': self.estimated_tokens_used,
                'tokens_available': self.max_tokens_available,
                'context_usage_percent': usage_percent,
                'blocked': False,
                'reason': f'API Error: {str(e)}'
            }
        finally:
            spinner.stop()
    
    def reset(self):
        """Clear the chat session and start fresh."""
        self.chat_session = client.chats.create(
            model=MODEL,
            config=chat_config
        )
        self.estimated_tokens_used = self._estimate_tokens(self.system_prompt)
        return "✓ Chat session reset"
    
    def get_status(self):
        """Get current session status."""
        return {
            'tokens_used': self.estimated_tokens_used,
            'tokens_available': self.max_tokens_available,
            'context_usage_percent': self._get_context_usage_percent(),
            'is_full': self._is_context_full(),
            'model': MODEL
        }

# ═══════════════════════════════════════════════════════════════════════════
# Interactive CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 80)
    print("  Gemini Chat Session with Context Management")
    print("=" * 80)
    print("Commands:")
    print("  'exit' or 'quit'  - End the conversation")
    print("  'reset'           - Clear session and start fresh")
    print("  'status'          - Show token usage and context status")
    print("=" * 80)
    print()
    
    # Create a persistent session
    session = ChatSession()
    print()
    
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            # Handle special commands
            if user_input.lower() in ['exit', 'quit']:
                print("\nGoodbye!")
                break
            
            if user_input.lower() == 'reset':
                print(session.reset())
                print("Ready for new conversation.\n")
                continue
            
            if user_input.lower() == 'status':
                status = session.get_status()
                print(f"\n╭─ Context Status")
                print(f"├─ Model: {status['model']}")
                print(f"├─ Tokens Used: {status['tokens_used']:,} / {status['tokens_available']:,}")
                print(f"├─ Usage: {status['context_usage_percent']:.1f}%")
                print(f"└─ Status: {'⚠ FULL (approaching limit)' if status['is_full'] else '✓ Available'}")
                print()
                continue
            
            # Skip empty input
            if not user_input:
                continue
            
            # Send message with context checks
            result = session.send_message(user_input)
            
            if result['blocked']:
                print(f"\n❌ Message Blocked: {result['reason']}")
                print(f"   Context at {result['context_usage_percent']:.1f}%")
                print("   Use 'reset' to start a new conversation.\n")
            elif result['success']:
                print(f"\nGemini: {result['response']}\n")
                print(f"[Context: {result['context_usage_percent']:.1f}% • " +
                      f"{result['tokens_used']:,} / {result['tokens_available']:,} tokens]\n")
            else:
                print(f"\n⚠ Error: {result['reason']}\n")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}\n")