import logging
import os
import yaml
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.call_llm import call_llm
from utils.crawl_local_files import crawl_local_files

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# Helper to get content for specific file indices
def get_content_for_indices(files_data, indices):
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = (
                content  # Use index + path as key for context
            )
    return content_map


class FetchRepo(Node):
    def prep(self, shared):
        repo_url = shared.get("repo_url")
        local_dir = shared.get("local_dir")
        project_name = shared.get("project_name")

        if not project_name:
            # Basic name derivation from URL or directory
            if repo_url:
                project_name = repo_url.split("/")[-1].replace(".git", "")
            else:
                project_name = os.path.basename(os.path.abspath(local_dir))
            shared["project_name"] = project_name

        # Get file patterns directly from shared
        include_patterns = shared["include_patterns"]
        exclude_patterns = shared["exclude_patterns"]
        max_file_size = shared["max_file_size"]

        return {
            "repo_url": repo_url,
            "local_dir": local_dir,
            "token": shared.get("github_token"),
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "max_file_size": max_file_size,
            "use_relative_paths": True,
        }

    def exec(self, prep_res):
        if prep_res["repo_url"]:
            logging.info(f"Crawling repository: {prep_res['repo_url']}...")
            result = crawl_github_files(
                repo_url=prep_res["repo_url"],
                token=prep_res["token"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"],
            )
        else:
            logging.info(f"Crawling directory: {prep_res['local_dir']}...")
            result = crawl_local_files(
                directory=prep_res["local_dir"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"],
            )

        # Convert dict to list of tuples: [(path, content), ...]
        files_list = list(result.get("files", {}).items())
        if len(files_list) == 0:
            raise (ValueError("Failed to fetch files"))
        logging.info(f"Fetched {len(files_list)} files.")
        return files_list

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res  # List of (path, content) tuples


class IdentifyAbstractions(Node):
    def prep(self, shared):
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name

        # Helper to create context from files, respecting limits (basic example)
        def create_llm_context(files_data):
            context = ""
            file_info = []  # Store tuples of (index, path)
            for i, (path, content) in enumerate(files_data):
                entry = f"--- File Index {i}: {path} ---\n{content}\n\n"
                context += entry
                file_info.append((i, path))

            return context, file_info  # file_info is list of (index, path)

        context, file_info = create_llm_context(files_data)
        # Format file info for the prompt (comment is just a hint for LLM)
        file_listing_for_prompt = "\n".join(
            [f"- {idx} # {path}" for idx, path in file_info]
        )
        return (
            context,
            file_listing_for_prompt,
            len(files_data),
            project_name,
        )

    def exec(self, prep_res):
        context, file_listing_for_prompt, file_count, project_name = (
            prep_res  # Unpack project name and other extracted data
        )
        logging.info("Identifying abstractions using LLM...")

        prompt = f"""
For the project `{project_name}`:

Codebase Context:
{context}

Analyze the codebase context.
Identify the top 5-10 core most important abstractions to help an AI coding agent new to the codebase.

For each abstraction, provide:
1. A concise `name`.
2. An knowledge-dense `description` explaining what it does and when to use it with references to the specific problems that it solves and software engineering concepts that it uses, such as design patterns, data structures, algorithms etc. if applicable , in around 200 words.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Node
  description: |
    Explains what the abstraction does.
    It is the base class used to build directed graphs.
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
- name: |
    Flow
  description: |
    It is composed of multiple nodes connected to each other to define a conditional execution of any workflow.
  file_indices:
    - 5 # path/to/another.js
# ... up to 10 abstractions
```"""
        response = call_llm(prompt)

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        abstractions = yaml.safe_load(yaml_str)

        if not isinstance(abstractions, list):
            raise ValueError("LLM Output is not a list")

        validated_abstractions = []
        for item in abstractions:
            if not isinstance(item, dict) or not all(
                k in item for k in ["name", "description", "file_indices"]
            ):
                raise ValueError(f"Missing keys in abstraction item: {item}")
            if not isinstance(item["name"], str):
                raise ValueError(f"Name is not a string in item: {item}")
            if not isinstance(item["description"], str):
                raise ValueError(f"Description is not a string in item: {item}")
            if not isinstance(item["file_indices"], list):
                raise ValueError(f"file_indices is not a list in item: {item}")

            # Validate indices
            validated_indices = []
            for idx_entry in item["file_indices"]:
                try:
                    if isinstance(idx_entry, int):
                        idx = idx_entry
                    elif isinstance(idx_entry, str) and "#" in idx_entry:
                        idx = int(idx_entry.split("#")[0].strip())
                    else:
                        idx = int(str(idx_entry).strip())

                    if not (0 <= idx < file_count):
                        raise ValueError(
                            f"Invalid file index {idx} found in item {item['name']}. Max index is {file_count - 1}."
                        )
                    validated_indices.append(idx)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Could not parse index from entry: {idx_entry} in item {item['name']}"
                    )

            item["files"] = sorted(list(set(validated_indices)))
            # Store only the required fields
            validated_abstractions.append(
                {
                    "name": item["name"].strip(),
                    "description": item["description"].strip(),
                    "files": item["files"],
                }
            )

        logging.info(f"Identified {len(validated_abstractions)} abstractions.")
        return validated_abstractions

    def post(self, shared, prep_res, exec_res):
        shared["abstractions"] = (
            exec_res  # List of {"name": str, "description": str, "files": [int]}
        )


class AnalyzeRelationships(Node):
    def prep(self, shared):
        abstractions = shared["abstractions"]  # Now contains 'files' list of indices
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name

        # Create context with abstraction names, indices, descriptions, and relevant file snippets
        context = "Identified Abstractions:\n"
        all_relevant_indices = set()
        abstraction_info_for_prompt = []
        for i, abstr in enumerate(abstractions):
            # Use 'files' which contains indices directly
            file_indices_str = ", ".join(map(str, abstr["files"]))
            info_line = f"- Index {i}: {abstr['name']} (Relevant file indices: [{file_indices_str}])\n  Description: {abstr['description']}"
            context += info_line + "\n"
            abstraction_info_for_prompt.append(f"{i} # {abstr['name']}")
            all_relevant_indices.update(abstr["files"])

        context += "\nRelevant File Snippets (Referenced by Index and Path):\n"
        # Get content for relevant files using helper
        relevant_files_content_map = get_content_for_indices(
            files_data, sorted(list(all_relevant_indices))
        )
        # Format file content for context
        file_context_str = "\n\n".join(
            f"--- File: {idx_path} ---\n{content}"
            for idx_path, content in relevant_files_content_map.items()
        )
        context += file_context_str

        return (
            context,
            "\n".join(abstraction_info_for_prompt),
            project_name,
        )

    def exec(self, prep_res):
        context, abstraction_listing, project_name = (
            prep_res  # Unpack project name and other extracted data
        )
        logging.info("Analyzing relationships using LLM...")

        prompt = f"""
Based on the following abstractions and relevant code snippets from the project `{project_name}`:

List of Abstraction Indices and Names:
{abstraction_listing}

Context (Abstractions, Descriptions, Code):
{context}

Please provide:
1. A technical `summary` of the project's main purpose and functionality in a style similar to a transfer document with references to relevant software engineering concepts if applicable. Use markdown formatting with **bold** and *italic* text to highlight important concepts.
2. A list (`relationships`) describing the key interactions between these abstractions. For each relationship, specify:
    - `from_abstraction`: Index of the source abstraction (e.g., `0 # AbstractionName1`)
    - `to_abstraction`: Index of the target abstraction (e.g., `1 # AbstractionName2`)
    - `label`: A brief label for the interaction **in just a few words** (e.g., "Manages", "Inherits", "Uses").
    Ideally the relationship should be backed by one abstraction calling or passing parameters to another.
    Simplify the relationship and exclude those non-important ones.

IMPORTANT: Make sure EVERY abstraction is involved in at least ONE relationship (either as source or target). Each abstraction index must appear at least once across all relationships.

Format the output as YAML:

```yaml
summary: |
  A brief, technical explanation of the project.
  Can span multiple lines with **bold** and *italic* for emphasis.
  Think of it as a transfer document summarizing the architecture and/or design, overview of problems tackled, solutions provided and conventions followed from the perspective of software engineering.
relationships:
  - from_abstraction: 0 # AbstractionName1
    to_abstraction: 1 # AbstractionName2
    label: "Manages"
  - from_abstraction: 2 # AbstractionName3
    to_abstraction: 0 # AbstractionName1
    label: "Provides config"
  # ... other relationships
```

Now, provide the YAML output:
"""
        response = call_llm(prompt)

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        relationships_data = yaml.safe_load(yaml_str)

        if not isinstance(relationships_data, dict) or not all(
            k in relationships_data for k in ["summary", "relationships"]
        ):
            raise ValueError(
                "LLM output is not a dict or missing keys ('summary', 'relationships')"
            )
        if not isinstance(relationships_data["summary"], str):
            raise ValueError("summary is not a string")
        if not isinstance(relationships_data["relationships"], list):
            raise ValueError("relationships is not a list")

        # Validate relationships structure
        validated_relationships = []
        num_abstractions = len(abstraction_listing.split("\n"))
        for rel in relationships_data["relationships"]:
            # Check for 'label' key
            if not isinstance(rel, dict) or not all(
                k in rel for k in ["from_abstraction", "to_abstraction", "label"]
            ):
                raise ValueError(
                    f"Missing keys (expected from_abstraction, to_abstraction, label) in relationship item: {rel}"
                )
            # Validate 'label' is a string
            if not isinstance(rel["label"], str):
                raise ValueError(f"Relationship label is not a string: {rel}")

            # Validate indices
            try:
                from_idx = int(str(rel["from_abstraction"]).split("#")[0].strip())
                to_idx = int(str(rel["to_abstraction"]).split("#")[0].strip())
                if not (
                    0 <= from_idx < num_abstractions and 0 <= to_idx < num_abstractions
                ):
                    raise ValueError(
                        f"Invalid index in relationship: from={from_idx}, to={to_idx}. Max index is {num_abstractions - 1}."
                    )
                validated_relationships.append(
                    {
                        "from": from_idx,
                        "to": to_idx,
                        "label": rel["label"],  # Potentially translated label
                    }
                )
            except (ValueError, TypeError):
                raise ValueError(f"Could not parse indices from relationship: {rel}")

        logging.info("Generated project summary and relationship details.")
        return {
            "summary": relationships_data["summary"],  # Potentially translated summary
            "details": validated_relationships,  # Store validated, index-based relationships with potentially translated labels
        }

    def post(self, shared, prep_res, exec_res):
        # Structure is now {"summary": str, "details": [{"from": int, "to": int, "label": str}]}
        shared["relationships"] = exec_res


class OrderChapters(Node):
    def prep(self, shared):
        abstractions = shared["abstractions"]
        relationships = shared["relationships"]
        project_name = shared["project_name"]  # Get project name

        # Prepare context for the LLM
        abstraction_info_for_prompt = []
        for i, a in enumerate(abstractions):
            abstraction_info_for_prompt.append(f"- {i} # {a['name']}")
        abstraction_listing = "\n".join(abstraction_info_for_prompt)

        context = f"Project Summary:\n{relationships['summary']}\n\n"
        context += "Relationships (Indices refer to abstractions above):\n"
        for rel in relationships["details"]:
            from_name = abstractions[rel["from"]]["name"]
            to_name = abstractions[rel["to"]]["name"]
            # Use potentially translated 'label'
            context += f"- From {rel['from']} ({from_name}) to {rel['to']} ({to_name}): {rel['label']}\n"  # Label might be translated

        return (
            abstraction_listing,
            context,
            len(abstractions),
            project_name,
        )

    def exec(self, prep_res):
        abstraction_listing, context, num_abstractions, project_name = prep_res
        logging.info("Determining chapter order using LLM...")
        prompt = f"""
Given the following project abstractions and their relationships for the project ```` {project_name} ````:

Abstractions (Index # Name):
{abstraction_listing}

Context about relationships and project summary:
{context}

If you are going to make a tutorial for ```` {project_name} ````, what is the best order to explain these abstractions, from first to last?
Ideally, first explain those that are the most important or foundational, perhaps user-facing concepts or entry points. Then move to more detailed, lower-level implementation details or supporting concepts.

Output the ordered list of abstraction indices, including the name in a comment for clarity. Use the format `idx # AbstractionName`.

```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
- 1 # CoreClassB (uses CoreClassA)
- ...
```

Now, provide the YAML output:
"""
        response = call_llm(prompt)

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        ordered_indices_raw = yaml.safe_load(yaml_str)

        if not isinstance(ordered_indices_raw, list):
            raise ValueError("LLM output is not a list")

        ordered_indices = []
        seen_indices = set()
        for entry in ordered_indices_raw:
            try:
                if isinstance(entry, int):
                    idx = entry
                elif isinstance(entry, str) and "#" in entry:
                    idx = int(entry.split("#")[0].strip())
                else:
                    idx = int(str(entry).strip())

                if not (0 <= idx < num_abstractions):
                    raise ValueError(
                        f"Invalid index {idx} in ordered list. Max index is {num_abstractions - 1}."
                    )
                if idx in seen_indices:
                    raise ValueError(f"Duplicate index {idx} found in ordered list.")
                ordered_indices.append(idx)
                seen_indices.add(idx)

            except (ValueError, TypeError):
                raise ValueError(
                    f"Could not parse index from ordered list entry: {entry}"
                )

        # Check if all abstractions are included
        if len(ordered_indices) != num_abstractions:
            raise ValueError(
                f"Ordered list length ({len(ordered_indices)}) does not match number of abstractions ({num_abstractions}). Missing indices: {set(range(num_abstractions)) - seen_indices}"
            )

        logging.info(f"Determined chapter order (indices): {ordered_indices}")
        return ordered_indices  # Return the list of indices

    def post(self, shared, prep_res, exec_res):
        # exec_res is already the list of ordered indices
        shared["chapter_order"] = exec_res  # List of indices


class WriteChapters(BatchNode):
    def prep(self, shared):
        chapter_order = shared["chapter_order"]  # List of indices
        abstractions = shared["abstractions"]  # List of dicts
        files_data = shared["files"]

        # Get already written chapters to provide context
        # We store them temporarily during the batch run, not in shared memory yet
        # The 'previous_chapters_summary' will be built progressively in the exec context
        self.chapters_written_so_far = []  # Use instance variable for temporary storage across exec calls

        # Create a complete list of all chapters
        all_chapters = []
        chapter_filenames = {}  # Store chapter filename mapping for linking
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                chapter_num = i + 1
                chapter_name = abstractions[abstraction_index][
                    "name"
                ]  # Potentially translated name
                # Create safe filename (from potentially translated name)
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in chapter_name
                ).lower()
                filename = f"{safe_name}.mdc"
                # Format with link (using potentially translated name)
                all_chapters.append(f"[{chapter_name}]({filename})")
                # Store mapping of chapter index to filename for linking
                chapter_filenames[abstraction_index] = {
                    "num": chapter_num,
                    "name": chapter_name,
                    "filename": filename,
                }

        # Create a formatted string with all chapters
        full_chapter_listing = "\n".join(all_chapters)

        items_to_process = []
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                abstraction_details = abstractions[abstraction_index]
                # Use 'files' (list of indices) directly
                related_file_indices = abstraction_details.get("files", [])
                # Get content using helper, passing indices
                related_files_content_map = get_content_for_indices(
                    files_data, related_file_indices
                )

                # Get previous chapter info for transitions (uses potentially translated name)
                prev_chapter = None
                if i > 0:
                    prev_idx = chapter_order[i - 1]
                    prev_chapter = chapter_filenames[prev_idx]

                # Get next chapter info for transitions (uses potentially translated name)
                next_chapter = None
                if i < len(chapter_order) - 1:
                    next_idx = chapter_order[i + 1]
                    next_chapter = chapter_filenames[next_idx]

                items_to_process.append(
                    {
                        "chapter_num": i + 1,
                        "abstraction_index": abstraction_index,
                        "abstraction_details": abstraction_details,
                        "related_files_content_map": related_files_content_map,
                        "project_name": shared["project_name"],  # Add project name
                        "full_chapter_listing": full_chapter_listing,  # Add the full chapter listing
                        "chapter_filenames": chapter_filenames,
                        "prev_chapter": prev_chapter,
                        "next_chapter": next_chapter,  # Add next chapter info
                        # previous_chapters_summary will be added dynamically in exec
                    }
                )
            else:
                logging.warning(
                    f"Invalid abstraction index {abstraction_index} in chapter_order. Skipping."
                )

        logging.info(f"Preparing to write {len(items_to_process)} chapters...")
        return items_to_process  # Iterable for BatchNode

    def exec(self, item):
        # This runs for each item prepared above
        abstraction_name = item["abstraction_details"]["name"]
        abstraction_description = item["abstraction_details"]["description"]
        chapter_num = item["chapter_num"]
        project_name = item.get("project_name")
        logging.info(
            f"Writing chapter {chapter_num} for: {abstraction_name} using LLM..."
        )

        # Prepare file context string from the map
        file_context_str = "\n\n".join(
            f"--- File: {idx_path.split('# ')[1] if '# ' in idx_path else idx_path} ---\n{content}"
            for idx_path, content in item["related_files_content_map"].items()
        )

        # Get summary of chapters written *before* this one
        # Use the temporary instance variable
        previous_chapters_summary = "\n---\n".join(self.chapters_written_so_far)

        prompt = f"""
Write a highly informative and technical tutorial chapter to teach the following concept in the project `{project_name}` to a coding AI agent: "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Tutorial Structure:
{item["full_chapter_listing"]}

Context from previous chapters:
{previous_chapters_summary if previous_chapters_summary else "This is the first chapter."}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str if file_context_str else "No specific code snippets provided for this abstraction."}

Instructions for the chapter:
- Output in YAML format. Provide `description`, `globs` and `alwaysApply` metadata in addition to the chapter `content` in Markdown format.
- Start `content` with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided concept name.
- Prepend the Markdown content with metadata described below to tell the AI agent when to refer to this particular chapter:

```yaml
description: "A 10-15-word description containing the project name and abstractions / concepts detailed in this chapter. AI will decide when to refer to this chapter based on this description."
globs: Empty or a single glob pattern string. If matched with a code file, it will be automatically picked by the AI agent whenever that file is mentioned. Empty string almost all the time. Set it to a pattern only for **very, very specific abstractions**, e.g., a single class in a file.
alwaysApply: false almost all the time. set it to true only for **very, very central abstractions**.
content: |
  Full chapter content in Markdown format.
  It can span to multiple lines and paragraphs.
  You can use **bold** and *italic* texts for emphasis.
```

- If this is not the first chapter, begin with a brief transition from the previous chapter referencing it with a proper Markdown link using its name.

- Begin with a high-level motivation explaining what technical problem this abstraction solves. Continue with a central use case as a concrete example. The whole chapter should guide the coding AI agent to understand how to make use of it when developing with or for it.

- If the abstraction is complex, break it down into key concepts. Explain each concept one-by-one in a very concrete way.

- Explain how to use this abstraction to solve the use case. Give example inputs and outputs for code snippets (if the output isn't values, describe at a high level what will happen). Mention about default and/or optional values, if applicable.

- Focus on practical usage examples and code architecture. Remember that the output will be used by a less-capable coding agent, so be direct and authoritative.

- Each code block should be BELOW 20 lines! If longer code blocks are needed, break them down into smaller pieces and walk through them one-by-one. Aggresively simplify the code to make it minimal. Use comments to skip non-important implementation details. Each code block should have a technical explanation right after it.

- Describe the internal implementation to help understand what's under the hood. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called. It's recommended to examplify inputs and outputs if applicable.

- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but keep it minimal  and knowledge-dense, and do so only to help the AI agent better understand the inner working of the code at a higher level.

- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Tutorial Structure above to find the correct filename and the chapter title.

- Properly use technical terms and software engineering concepts throughout to help the coding AI agent develop with and/or for this project.

- End the chapter with a brief conclusion that summarizes what was learned and provides a transition to the next chapter. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename).

- Ensure the tone is technical and informatory.

Now provide the YAML output for this chapter.
"""
        response = call_llm(prompt)
        yaml_str = response.strip().split("```yaml")[1].rstrip("```")
        chapter_data = yaml.safe_load(yaml_str)

        # Basic validation/cleanup
        if not isinstance(chapter_data, dict) or not all(
            k in chapter_data
            for k in ["description", "globs", "alwaysApply", "content"]
        ):
            raise ValueError(
                "LLM output is not a dictionary or has missing keys", chapter_data
            )

        if chapter_data["globs"] is None or (
            isinstance(chapter_data["globs"], list) and len(chapter_data["globs"]) == 0
        ):
            chapter_data["globs"] = " "
        elif isinstance(chapter_data["globs"], str):
            chapter_data["globs"] = chapter_data["globs"].strip()

        if not all(isinstance(k, str) for k in ["description", "globs", "content"]):
            raise ValueError(
                "description, globs or content is not a string", chapter_data
            )

        if not isinstance(chapter_data["alwaysApply"], bool):
            raise ValueError("alwaysApply is not a bool", chapter_data["alwaysApply"])

        chapter_content = chapter_data["content"]
        actual_heading = f"# Chapter {chapter_num}: {abstraction_name}"
        if not chapter_content.strip().startswith(f"# Chapter {chapter_num}"):
            # Add heading if missing or incorrect, trying to preserve content
            lines = chapter_content.strip().split("\n")
            if lines and lines[0].strip().startswith(
                "#"
            ):  # If there's some heading, replace it
                lines[0] = actual_heading
                chapter_content = "\n".join(lines)
            else:  # Otherwise, prepend it
                chapter_content = f"{actual_heading}\n\n{chapter_content}"

        # prepare the frontmatter and
        frontmatter = "---\ndescription: "
        frontmatter += chapter_data["description"].strip()
        frontmatter += "\nglobs: "
        frontmatter += chapter_data["globs"].strip()
        frontmatter += "\nalwaysApply: "
        frontmatter += "true" if chapter_data["alwaysApply"] else "false"
        frontmatter += "\n---\n"

        # prepend it to the chapter content
        chapter_content = frontmatter + chapter_content

        # Add the generated content to our temporary list for the next iteration's context
        self.chapters_written_so_far.append(chapter_content)

        return chapter_content

    def post(self, shared, prep_res, exec_res_list):
        # exec_res_list contains the generated Markdown for each chapter, in order
        shared["chapters"] = exec_res_list
        # Clean up the temporary instance variable
        del self.chapters_written_so_far
        logging.info(f"Finished writing {len(exec_res_list)} chapters.")


class CombineTutorial(Node):
    def prep(self, shared):
        project_name = shared["project_name"]
        output_base_dir = shared.get("output_dir", "output")  # Default output dir
        output_path = os.path.join(output_base_dir, project_name)
        repo_url = shared.get("repo_url")  # Get the repository URL

        # Get potentially translated data
        relationships_data = shared[
            "relationships"
        ]  # {"summary": str, "details": [{"from": int, "to": int, "label": str}]}
        chapter_order = shared["chapter_order"]  # indices
        abstractions = shared["abstractions"]  # list of dicts
        chapters_content = shared["chapters"]  # list of strings

        # --- Prepare guide.mdc content ---
        index_content = f"---\ndescription: Guidelines for using {project_name}\nglobs: \nalwaysApply: true\n---\n"
        index_content += f"{relationships_data['summary']}\n\n"
        index_content += f"**Source Repository:** [{repo_url}]({repo_url})\n\n"

        index_content += "```\n\n"

        index_content += "## Chapters\n\n"

        chapter_files = []
        # Generate chapter links based on the determined order, using potentially translated names
        for i, abstraction_index in enumerate(chapter_order):
            # Ensure index is valid and we have content for it
            if 0 <= abstraction_index < len(abstractions) and i < len(chapters_content):
                abstraction_name = abstractions[abstraction_index]["name"]
                # Sanitize potentially translated name for filename
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in abstraction_name
                ).lower()
                filename = f"{safe_name}.mdc"
                index_content += f"[{abstraction_name}]({filename})\n"

                # Add attribution to chapter content
                chapter_content = chapters_content[i]
                if not chapter_content.endswith("\n\n"):
                    chapter_content += "\n\n"
                chapter_content += "---\n\nGenerated by [Rules for AI](https://github.com/altaidevorg/rules-for-ai)"

                # Store filename and corresponding content
                chapter_files.append({"filename": filename, "content": chapter_content})
            else:
                logging.warning(
                    f"Mismatch between chapter order, abstractions, or content at index {i} (abstraction index {abstraction_index}). Skipping file generation for this entry."
                )

        # Add attribution to index content
        index_content += "\n\n---\n\nGenerated by [Rules for AI](https://github.com/altaidevorg/rules-for-ai)"

        return {
            "output_path": output_path,
            "index_content": index_content,
            "chapter_files": chapter_files,  # List of {"filename": str, "content": str}
        }

    def exec(self, prep_res):
        output_path = prep_res["output_path"]
        index_content = prep_res["index_content"]
        chapter_files = prep_res["chapter_files"]

        logging.info(f"Combining rules into directory: {output_path}")
        # Rely on Node's built-in retry/fallback
        os.makedirs(output_path, exist_ok=True)

        # Write guide.mdc
        index_filepath = os.path.join(output_path, "guide.mdc")
        with open(index_filepath, "w", encoding="utf-8") as f:
            f.write(index_content)
        logging.info(f"  - Wrote {index_filepath}")

        # Write chapter files
        for chapter_info in chapter_files:
            chapter_filepath = os.path.join(output_path, chapter_info["filename"])
            with open(chapter_filepath, "w", encoding="utf-8") as f:
                f.write(chapter_info["content"])
            logging.info(f"  - Wrote {chapter_filepath}")

        return output_path  # Return the final path

    def post(self, shared, prep_res, exec_res):
        shared["final_output_dir"] = exec_res  # Store the output path
        logging.info(f"\n.cursor/rules generation complete! Files are in: {exec_res}")
