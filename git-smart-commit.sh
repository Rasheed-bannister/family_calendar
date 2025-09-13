#!/bin/bash
# Smart commit script that handles pre-commit auto-fixes automatically

commit_with_message() {
    if [ $# -eq 0 ]; then
        echo "Usage: $0 <commit-message>"
        exit 1
    fi

    local attempt=1
    local max_attempts=5

    while [ $attempt -le $max_attempts ]; do
        echo "🔄 Commit attempt $attempt/$max_attempts..."

        if git commit -m "$*"; then
            echo "✅ Commit successful!"
            exit 0
        fi

        if [ $attempt -eq $max_attempts ]; then
            echo "❌ Maximum attempts reached. Commit failed after $max_attempts tries."
            echo "This usually means there are unfixable issues. Please check manually."
            exit 1
        fi

        echo "Pre-commit hooks made changes. Adding them and retrying..."
        git add -u  # Add all modified tracked files

        attempt=$((attempt + 1))
        sleep 1  # Brief pause between attempts
    done
}

# Run the commit with all arguments as the commit message
commit_with_message "$@"
