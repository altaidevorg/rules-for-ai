<h1 align="center">Turns Codebase into Cursor Rules with AI</h1>

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

> *Why bother reading a whole tutorial in the days of agentic coding? This is an AI agent that analyzes GitHub repositories and creates [Cursor Rules](https://docs.cursor.com/context/rules) that teaches AI how to develop with and/or for them.*

This is a project inspired by and forked from [a great project of Pocket Flow](https://github.com/The-Pocket/Tutorial-Codebase-Knowledge), which generates tutorials for humans. We just thought, **tutorials are for humans, rules are for AI**. Hence, we modified it to generate [Cursor Rules](https://docs.cursor.com/context/rules) instead of beginner-friendly tutorials for humans. It crawls GitHub repositories and builds a knowledge base from the code. It analyzes entire codebases to identify core abstractions and how they interact, and creates `Project Rules` with code samples, default and optional values, architecture and design patterns, and an overview of the inner working of the code.

**Cursor rules**:

 > Control how the Agent model behaves with reusable, scoped instructions.
 >
 > Rules allow you to provide system-level guidance to the Agent and Cmd-K AI. Think of them as a persistent way to encode context, preferences, or workflows for your projects or for yourself.

*Having Cursor Rules is especially useful for developing with recent releases or developing for your own codebase.*

## ⭐ Example Results

🤯 All these Cursor Rules are generated **entirely by AI** by crawling the GitHub repo!

- [flax](https://github.com/altaidevorg/rules-for-ai/blob/main/examples/flax/guide.mdc) - Flax is neural network library for JAX that is designed for flexibility.
- [google-genai](https://github.com/altaidevorg/rules-for-ai/blob/main/examples/google-genai/guide.mdc) - Google Gen AI Python SDK provides an interface for developers to integrate Google's generative models into their Python applications.
- [google-adk](https://github.com/altaidevorg/rules-for-ai/blob/main/examples/google-adk/guide.mdc) - An open-source, code-first Python toolkit for building, evaluating, and deploying sophisticated AI agents with flexibility and control.
- [letsearch](https://github.com/altaidevorg/letsearch/blob/main/.cursor/rules/guide.mdc) - A vector DB so easy, even your grandparents can build a RAG system.
- [letsearch-client](https://github.com/altaidevorg/letsearch-client/blob/main/.cursor/rules/guide.mdc) - Python client for letsearch.

- Tell us in [Discussions](https://github.com/altaidevorg/rules-for-ai/discussions) how you're using AI-generated Cursor Rules and how it's contributing to your agentic coding experience!

## 🚀 Getting Started

1. Clone this repository and then set you `GEMINI_API_KEY` environment variable:

```bash
export GEMINI_API_KEY=your_api_key_here
```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Generate a complete codebase tutorial by running the main script:

    ```bash
    # Analyze a GitHub repository
    python main.py --repo https://github.com/username/repo --include "*.py" "*.js" --exclude "tests/*" --max-size 50000

    # Or, analyze a local directory
    python main.py --dir /path/to/your/codebase --include "*.py" --exclude "*test*"
    ```

    - `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive)
    - `-n, --name` - Project name (optional, derived from URL/directory if omitted)
    - `-t, --token` - GitHub token (or set GITHUB_TOKEN environment variable)
    - `-o, --output` - Output directory (default: ./output)
    - `-i, --include` - Files to include (e.g., "*.py" "*.js")
    - `-e, --exclude` - Files to exclude (e.g., "tests/*" "docs/*")
    - `-s, --max-size` - Maximum file size in bytes (default: 100KB)

The application will crawl the repository, analyze the codebase structure, generate  Cursor Rules, and save the output in the specified directory (default: ./output).
