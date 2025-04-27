import os
import logging
import google.generativeai as genai

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Configure Google Generative AI
# It's best practice to load the API key from environment variables
# Ensure you have GOOGLE_API_KEY set in your environment
try:
    api_key = os.environ.get("ALTAI_GEMINI_API_KEY")
    if not api_key:
        logging.warning(
            "GEMINI_API_KEY environment variable not set. Gemini calls may fail."
        )
        # You might choose to raise an error or handle this case differently
    genai.configure(api_key=api_key)
    # Initialize the model (e.g., Gemini 1.5 Flash)
    # Choose the appropriate model name
    gemini_model = genai.GenerativeModel("gemini-2.5-pro-preview-03-25")
    logging.info("Google Generative AI configured successfully.")
except Exception as e:
    logging.error(f"Failed to configure Google Generative AI: {e}")
    gemini_model = None


def call_llm(prompt: str) -> str:
    """
    Calls the configured Google Gemini model with the given prompt.

    Args:
        prompt: The input prompt for the LLM.

    Returns:
        The text content of the LLM's response.

    Raises:
        Exception: If the API call fails or the model is not configured.
    """
    if gemini_model is None:
        raise RuntimeError("LLM model not initialized.")

    logging.info(
        f"Calling LLM model with prompt: {prompt[:100]}..."
    )  # Log first 100 chars
    try:
        response = gemini_model.generate_content(prompt)
        # Basic error handling for response structure
        if not response.parts:
            logging.warning(f"LLM response for prompt '{prompt[:50]}...' had no parts.")
            # Check for safety ratings or blockages
            if response.prompt_feedback.block_reason:
                logging.error(
                    f"LLM call blocked. Reason: {response.prompt_feedback.block_reason}"
                )
                return f"Error: Content generation blocked due to {response.prompt_feedback.block_reason}."
            return "Error: Received an empty response from the model."

        content = response.text  # Access the text directly
        logging.info(
            f"LLM response received: {content[:100]}..."
        )  # Log first 100 chars
        return content
    except Exception as e:
        logging.error(f"LLM API call failed: {e}")
        # More specific error handling could be added here based on google.api_core.exceptions
        raise


if __name__ == "__main__":
    # Example usage (requires GEMINI_API_KEY environment variable)
    if os.environ.get("ALTAI_GEMINI_API_KEY") and gemini_model:
        test_prompt = "Explain the concept of Retrieval Augmented Generation (RAG) in one sentence."
        print(f"Testing call_llm with prompt: '{test_prompt}'")
        try:
            answer = call_llm(test_prompt)
            print(f"LLM Response: {answer}")
        except Exception as e:
            print(f"Error during test: {e}")
    elif not os.environ.get("ALTAI_GEMINI_API_KEY"):
        print(
            "Skipping call_llm test: ALTAI_GEMINI_API_KEY environment variable not set."
        )
    else:
        print("Skipping call_llm test: LLM model failed to initialize.")
