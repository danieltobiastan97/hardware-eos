import json
from google import genai
from google.genai import types
import warnings
from prompt import keys_and_prompt_setup, client_setup, Spinner, chat_client_setup

# Suppress the specific thought_signature warning from the SDK
warnings.filterwarnings("ignore", message=".*thought_signature.*")


with open('keys.json', 'r') as file:
    keys = json.load(file)
print('✓ API keys loaded successfully.')


keys, instruct = keys_and_prompt_setup(prompt_path='prompts/guardrail.txt')
print('✓ API keys and prompt loaded successfully.')
client, config = chat_client_setup(keys)

# ───────────────────────────────────────────────────────────────────────
# Create a simpler config without thinking for gemini-2.5-flash
# ───────────────────────────────────────────────────────────────────────
scraper_client = types.Tool(google_search=types.GoogleSearch())
chat_config = types.GenerateContentConfig(
    tools=[scraper_client]
    # Note: gemini-2.5-flash doesn't support thinking_level, so we removed it
)
print('✓ Gemini client and config set up successfully.')

# ═══════════════════════════════════════════════════════════════════════════
# Persistent Chat Context - Maintains conversation history across calls
# ═══════════════════════════════════════════════════════════════════════════
chat_history = []  # Persistent context across multiple chat() calls
system_instruction = instruct

def chat(user_message, config=None, system_prompt=None):
    """
    Send a message and maintain conversation context.
    
    Args:
        user_message: The user's input message
        config: GenerateContentConfig (optional, uses chat_config if not provided)
        system_prompt: Optional override for system instruction
        
    Returns:
        (response_text, full_chat_history): Tuple of Gemini's response and conversation history
    """
    global chat_history, system_instruction
    
    # Use provided config or default to chat_config (without thinking)
    use_config = config or chat_config
    
    # Use override system prompt if provided, otherwise use the global one
    current_system = system_prompt or system_instruction
    
    spinner = Spinner("Gemini is thinking")
    spinner.start()
    
    try:
        # Build message content: system instruction + conversation history + current message
        # Format: System instruction, then each previous exchange, then new user message
        message_parts = [current_system]
        
        # Add all previous messages to maintain context
        for sender, content in chat_history:
            prefix = f"\n{sender}: " if sender == "User" else f"\n{sender}: "
            message_parts.append(prefix + content)
        
        # Add the current user message
        message_parts.append(f"\nUser: {user_message}")
        
        # Concatenate all parts into a single string for generate_content
        full_content = "".join(message_parts)
        
        # Send to Gemini with full conversation history as concatenated string
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_content,
            config=use_config
        )
        
        # Store in persistent history
        chat_history.append(("User", user_message))
        chat_history.append(("Gemini", response.text))
        
        return response.text, chat_history
        
    finally:
        spinner.stop()

def clear_chat_history():
    """Clear the persistent chat history."""
    global chat_history
    chat_history = []
    print("✓ Chat history cleared")

def get_chat_history():
    """Get the current chat history."""
    return chat_history

# Example usage:
if __name__ == "__main__":
    print("=" * 70)
    print("  Interactive Chat with Persistent Context")
    print("=" * 70)
    print("Commands:")
    print("  'exit' or 'quit' - End the conversation")
    print("  'clear' - Clear chat history and start fresh")
    print("  'history' - Show full conversation history")
    print("=" * 70)
    print()
    
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            # Check for special commands
            if user_input.lower() in ['exit', 'quit']:
                print("\nGoodbye!")
                break
            
            if user_input.lower() == 'clear':
                clear_chat_history()
                print("Chat history cleared. Starting fresh.\n")
                continue
            
            if user_input.lower() == 'history':
                if not chat_history:
                    print("No conversation history yet.\n")
                else:
                    print("\n" + "=" * 70)
                    print("  Conversation History")
                    print("=" * 70)
                    for sender, msg in chat_history:
                        # Show first 200 chars for readability
                        display_msg = msg[:200] + "..." if len(msg) > 200 else msg
                        print(f"{sender}: {display_msg}")
                    print("=" * 70 + "\n")
                continue
            
            # Skip empty input
            if not user_input:
                continue
            
            # Send message and get response with persistent context
            response, history = chat(user_input)
            print(f"\nGemini: {response}\n")
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print("Please try again.\n")