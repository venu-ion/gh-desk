# SPDX-License-Identifier: Apache-2.0
"""GitHub field selections and view labels."""

TABS = ("Repositories", "Issues", "Pull requests", "Actions", "Projects")
REPO_FIELDS = (
    "nameWithOwner,description,isPrivate,isArchived,updatedAt,url,primaryLanguage,defaultBranchRef"
)
ISSUE_FIELDS = "number,title,body,state,url,labels,assignees,author,updatedAt"
PR_FIELDS = ISSUE_FIELDS + ",headRefName,baseRefName,isDraft,headRefOid,mergeable"
RUN_FIELDS = "databaseId,displayTitle,workflowName,status,conclusion,headBranch,createdAt,url"
