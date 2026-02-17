import logging
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.commits import PRMerge
from models.ch_models import PRMergeCH

logger = logging.getLogger(__name__)


async def check_pr_exists_ch(
    session: Session,
    repository_url: str,
    pr_number: int,
    installation_id: int,
) -> bool:
    """
    Check if a PR already exists in ClickHouse by (repository_url, pr_number, installation_id).        
    Returns:
        True if PR exists, False otherwise
    """
    try:
        count = session.query(func.count(PRMergeCH.pr_number)).filter(
            PRMergeCH.repository_url == repository_url,
            PRMergeCH.pr_number == pr_number,
            PRMergeCH.installation_id == installation_id,
        ).scalar()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking PR existence: {e}")
        return False


async def upsert_pr_ch(
    session: Session,
    pr_merge: PRMerge,
) -> bool:
    """
    Upsert a PR into ClickHouse using SQLAlchemy ORM.       
    Returns:
        True if successful, False otherwise
    """
    try:
        pr_merge_ch = PRMergeCH.from_pydantic(pr_merge)
        session.add(pr_merge_ch)
        session.commit()
        
        logger.info(
            f"Upserted PR event in ClickHouse: PR #{pr_merge.pr_number} "
            f"status={pr_merge.status}"
        )
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error upserting PR into ClickHouse: {e}")
        return False


async def process_pr_ch(
    pr_merge: PRMerge,
    session: Session,
    skip_existing: bool = False,
) -> Optional[PRMerge]:
    """
    Process and upsert a PR into ClickHouse using SQLAlchemy ORM.
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        if skip_existing:
            exists = await check_pr_exists_ch(
                session,
                pr_merge.repository_url,
                pr_merge.pr_number,
                pr_merge.installation_id,
            )
            if exists:
                logger.debug(
                    f"PR #{pr_merge.pr_number} already exists in ClickHouse, skipping"
                )
                return None
        
        # success = await upsert_pr_ch(session, pr_merge)
        print("PR-Merge: ", pr_merge)
        success = True
        if not success:
            return None
        
        return pr_merge
        
    except Exception as e:
        logger.error(
            f"Error processing PR {pr_merge.pr_number}: {e}",
            exc_info=True
        )
        return None


async def process_github_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    session: Session,
    skip_existing: bool = False,
) -> Optional[PRMerge]:
    """
    Process a GitHub PR event (opened, closed, merged) using ClickHouse.
    """
    try:
        pr_number = pr_data.get("number")
        pr_title = pr_data.get("title", "")
        pr_state = pr_data.get("state", "open")  # "open", "closed"
        merged = pr_data.get("merged", False)
        
        if not pr_number:
            logger.warning("PR event missing PR number")
            return None
        
        # Determine status: "open", "closed", or "merged"
        if pr_state == "open":
            status = "open"
        elif merged:
            status = "merged"
        else:
            status = "closed"
        
        # Extract merge commit hash (only for merged PRs)
        merge_commit_hash = pr_data.get("merge_commit_sha")
        merge_commit_hash_short = merge_commit_hash[:12] if merge_commit_hash else None
        
        # Extract created_by info (PR creator)
        user_info = pr_data.get("user", {})
        created_by_name = user_info.get("login", "Unknown") if user_info else "Unknown"
        created_by_email = user_info.get("email", "") if user_info else ""
        
        if not created_by_email:
            created_by_email = f"{created_by_name}@github.com"
        
        # Extract merged_by info (only for merged PRs)
        merged_by_info = pr_data.get("merged_by", {})
        merged_by_name = merged_by_info.get("login") if merged_by_info else None
        merged_by_email = merged_by_info.get("email") if merged_by_info else None
        
        if merged_by_name and not merged_by_email:
            merged_by_email = f"{merged_by_name}@github.com"
        
        # Extract branch name
        head_info = pr_data.get("head", {})
        branch = head_info.get("ref") if head_info else None
        
        # Extract additions and deletions
        additions = pr_data.get("additions")
        deletions = pr_data.get("deletions")
        
        # Extract dates
        created_at_str = pr_data.get("created_at")
        updated_at_str = pr_data.get("updated_at")
        merged_at_str = pr_data.get("merged_at")
        
        # Parse dates
        def parse_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")
                return datetime.fromisoformat(date_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse date {date_str}, using current time")
                return datetime.utcnow()
        
        # Use merged_at for merged PRs, created_at for opened, updated_at for closed
        if merged_at_str:
            date = parse_date(merged_at_str)
        elif created_at_str:
            date = parse_date(created_at_str)
        else:
            date = datetime.utcnow()
        
        updated_at = parse_date(updated_at_str) if updated_at_str else date
        
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            status=status,
            created_by=created_by_name,
            created_by_email=created_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=date,
            updated_at=updated_at,
            installation_id=installation_id,
            source="github",
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            branch=branch,
            additions=additions,
            deletions=deletions,
        )
        
        result = await process_pr_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing GitHub PR {pr_data.get('number', 'unknown')}: {e}", exc_info=True)
        return None


async def process_bitbucket_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    workspace_id: int,
    session: Session,
    skip_existing: bool = False,
) -> Optional[PRMerge]:
    """
    Process a Bitbucket PR event (created, updated, fulfilled, rejected) using ClickHouse.
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        pr_number = pr_data.get("id")
        pr_title = pr_data.get("title", "")
        
        if not pr_number:
            logger.warning("PR event missing PR ID")
            return None
        
        # Extract PR state and map to our status values
        pr_state = pr_data.get("state", "").upper()  # Bitbucket uses uppercase: "OPEN", "MERGED", "DECLINED", "SUPERSEDED"
        
        # Map Bitbucket states to our status values
        if pr_state == "OPEN":
            status = "open"
        elif pr_state == "MERGED":
            status = "merged"
        elif pr_state in ["DECLINED", "SUPERSEDED"]:
            status = "closed"
        else:
            # Default to open if state is unknown
            logger.warning(f"Unknown PR state '{pr_state}' for PR #{pr_number}, defaulting to 'open'")
            status = "open"
        
        # Extract merge commit hash (only for merged PRs)
        merge_commit_info = pr_data.get("merge_commit")
        if not merge_commit_info:
            merge_commit_info = pr_data.get("destination", {}).get("commit", {})
        
        merge_commit_hash = merge_commit_info.get("hash", "") if merge_commit_info else ""
        merge_commit_hash_short = merge_commit_hash[:12] if merge_commit_hash else None
        
        # Extract created_by info (PR creator)
        author_info = pr_data.get("author", {})
        created_by_name = author_info.get("display_name", "Unknown") if author_info else "Unknown"
        created_by_email = author_info.get("email", "") if author_info else ""
        
        if not created_by_email and "raw" in author_info:
            raw_author = author_info.get("raw", "")
            if " <" in raw_author and raw_author.endswith(">"):
                parts = raw_author.rsplit(" <", 1)
                created_by_name = parts[0]
                created_by_email = parts[1].rstrip(">")
        
        if not created_by_email:
            created_by_email = f"{created_by_name}@bitbucket.org"
        
        # Extract merged_by info (only for merged PRs)
        merged_by_name = None
        merged_by_email = None
        
        if status == "merged":
            # Check if there's separate merge information
            merge_info = pr_data.get("merge_commit", {}).get("author", {}) if pr_data.get("merge_commit") else {}
            if merge_info:
                merged_by_name = merge_info.get("display_name", created_by_name)
                merged_by_email = merge_info.get("email", created_by_email)
            else:
                # Default to author if no merge info
                merged_by_name = created_by_name
                merged_by_email = created_by_email
        
        # Extract branch name
        source_info = pr_data.get("source", {})
        branch_info = source_info.get("branch", {}) if source_info else {}
        branch = branch_info.get("name") if branch_info else None
        
        # Extract additions and deletions (may not be available in webhook payload)
        # Bitbucket webhook may not include diff stats, so these will be None
        additions = pr_data.get("summary", {}).get("additions") if pr_data.get("summary") else None
        deletions = pr_data.get("summary", {}).get("deletions") if pr_data.get("summary") else None
        
        # Extract dates
        created_at_str = pr_data.get("created_on")
        updated_at_str = pr_data.get("updated_on")
        closed_date_str = pr_data.get("closed_date")
        
        # Parse dates
        def parse_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")
                elif "+" not in date_str and "-" not in date_str[-6:]:
                    date_str = date_str + "+00:00"
                return datetime.fromisoformat(date_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse date {date_str}: {e}, using current time")
                return datetime.utcnow()
        
        # Use closed_date for closed/merged PRs, created_on for opened
        if closed_date_str:
            date = parse_date(closed_date_str)
        elif created_at_str:
            date = parse_date(created_at_str)
        else:
            date = datetime.utcnow()
        
        updated_at = parse_date(updated_at_str) if updated_at_str else date
        
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            status=status,
            created_by=created_by_name,
            created_by_email=created_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=date,
            updated_at=updated_at,
            installation_id=workspace_id,
            source="bitbucket",
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            branch=branch,
            additions=additions,
            deletions=deletions,
        )
        
        result = await process_pr_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket PR {pr_data.get('id', 'unknown')}: {e}", exc_info=True)
        return None
