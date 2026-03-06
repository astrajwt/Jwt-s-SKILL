---
name: github-repo-monitor
description: Monitor shader-slang/slang and vllm-project/vllm GitHub repos for new PRs and issues, generate a summary file.
---

Check the GitHub repositories **shader-slang/slang** and **vllm-project/vllm** for recent PR and Issue activity within the last hour.

## Steps

1. Use the `gh` CLI to fetch recent PRs and issues for both repos:
   - `gh pr list --repo shader-slang/slang --state all --limit 20 --json number,title,state,createdAt,updatedAt,author,url,labels`
   - `gh issue list --repo shader-slang/slang --state all --limit 20 --json number,title,state,createdAt,updatedAt,author,url,labels`
   - `gh pr list --repo vllm-project/vllm --state all --limit 20 --json number,title,state,createdAt,updatedAt,author,url,labels`
   - `gh issue list --repo vllm-project/vllm --state all --limit 20 --json number,title,state,createdAt,updatedAt,author,url,labels`

2. Filter results to only include items created or updated within the last ~1 hour (compare `updatedAt` timestamps against the current time).

3. Search for contribution opportunities — open issues the user could work on:
   - `gh issue list --repo shader-slang/slang --state open --label "good first issue" --limit 10 --json number,title,createdAt,url,labels,body`
   - `gh issue list --repo shader-slang/slang --state open --label "help wanted" --limit 10 --json number,title,createdAt,url,labels,body`
   - `gh issue list --repo vllm-project/vllm --state open --label "good first issue" --limit 10 --json number,title,createdAt,url,labels,body`
   - `gh issue list --repo vllm-project/vllm --state open --label "help wanted" --limit 10 --json number,title,createdAt,url,labels,body`
   - Also search for issues labeled "bug", "enhancement", or "feature" that have no assignee:
     `gh issue list --repo shader-slang/slang --state open --label "bug" --json number,title,url,labels,assignees,body --limit 10`
     `gh issue list --repo vllm-project/vllm --state open --label "bug" --json number,title,url,labels,assignees,body --limit 10`
   - Filter for unassigned issues (where assignees list is empty) as these are available for contribution.

4. Generate a Markdown summary file at `~/outputs/github-updates-YYYY-MM-DD-HH.md` (using the current date and hour). The file should contain:
   - A header with the check timestamp
   - **Recent Activity** section for each repo with sub-sections for PRs and Issues updated in the last hour
   - Each item should show: number, title, state, author, labels, and a clickable URL
   - If no updates were found for a repo, note "No updates in the last hour"
   - **Contribution Opportunities** section with:
     - Open "good first issue" and "help wanted" issues
     - Unassigned bug/enhancement issues that the user could pick up
     - For each issue, include a brief description of what needs to be done (from the issue body)

5. **Important**: After generating the file, directly tell the user in the conversation:
   - A brief summary of what changed in the last hour
   - Highlight any notable updates (new PRs, merged PRs, new issues)
   - **List specific open issues the user could work on**, with titles, links, and a one-line summary of each

## Output
- A Markdown file saved to the outputs folder
- A conversational notification with key updates and actionable issues the user can contribute to