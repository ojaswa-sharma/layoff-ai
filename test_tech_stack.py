"""
Test script for GitHub tech stack fetching and ClickHouse storage.

This script:
1. Fetches real tech stack data from GitHub API
2. Stores it in ClickHouse
3. Retrieves it from ClickHouse
4. Prints results to console

Environment variables required:
- APP_ID: GitHub App ID
- GITHUB_PEM_PATH: Path to GitHub App private key PEM file (default: isometrik.pem)
- REPOSITORY_FULL_NAME: Repository full name (owner/repo) to test
- INSTALLATION_ID: GitHub installation ID
"""
import asyncio
import os
from dotenv import load_dotenv
from dependencies.ch_db import init_ch_engine, get_ch_session_direct
from services.clickhouse_service.ch_tech_stack import (
    insert_or_update_tech_stack_ch,
    get_tech_stack_ch,
)
from services.tech_stack_service import fetch_github_tech_stack

load_dotenv()


def get_github_credentials():
    """Load GitHub App credentials from environment."""
    app_id = os.getenv("APP_ID")
    pem_path = os.getenv("GITHUB_PEM_PATH", "isometrik.pem")
    
    if not app_id:
        raise ValueError("APP_ID environment variable not set")
    
    if not os.path.exists(pem_path):
        raise FileNotFoundError(f"GitHub PEM file not found: {pem_path}")
    
    with open(pem_path, 'r') as file:
        pem_data = file.read()
    
    return app_id, pem_data


def print_separator():
    """Print a visual separator."""
    print("\n" + "=" * 80 + "\n")


def print_tech_stack_data(title: str, data: dict):
    """Print tech stack data in a formatted way."""
    print(f"\n{title}")
    print("-" * 80)
    print(f"Repository Full Name: {data.get('repository_full_name')}")
    print(f"Repository Name: {data.get('repository_name')}")
    print(f"Installation ID: {data.get('installation_id')}")
    print(f"Source: {data.get('source')}")
    print(f"Last Updated: {data.get('last_updated')}")
    
    languages = data.get('languages', {})
    if languages:
        print(f"\nLanguages ({len(languages)} total):")
        total_bytes = sum(languages.values())
        for lang, bytes_count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
            percentage = (bytes_count / total_bytes * 100) if total_bytes > 0 else 0
            print(f"  - {lang}: {bytes_count:,} bytes ({percentage:.1f}%)")
    else:
        print("\nLanguages: None")
    
    topics = data.get('topics', [])
    if topics:
        print(f"\nTopics ({len(topics)} total):")
        print(f"  {', '.join(topics)}")
    else:
        print("\nTopics: None")
    
    print("-" * 80)


async def main():
    """Main test function."""
    print_separator()
    print("GitHub Tech Stack Test Script")
    print_separator()
    
    # Load GitHub credentials
    print("Loading GitHub credentials...")
    try:
        app_id, pem_data = get_github_credentials()
        print(f"✓ GitHub credentials loaded (App ID: {app_id})")
    except Exception as e:
        print(f"✗ Failed to load GitHub credentials: {e}")
        return
    
    # Get repository and installation info from environment
    repository_full_name = os.getenv("REPOSITORY_FULL_NAME")
    installation_id_str = os.getenv("INSTALLATION_ID")
    
    if not repository_full_name:
        print("✗ REPOSITORY_FULL_NAME environment variable not set")
        print("  Example: REPOSITORY_FULL_NAME=owner/repo-name")
        return
    
    if not installation_id_str:
        print("✗ INSTALLATION_ID environment variable not set")
        print("  Example: INSTALLATION_ID=12345")
        return
    
    try:
        installation_id = int(installation_id_str)
    except ValueError:
        print(f"✗ INSTALLATION_ID must be a valid integer, got: {installation_id_str}")
        return
    
    # Extract repository name from full name
    repository_name = repository_full_name.split("/")[-1]
    
    print(f"✓ Repository: {repository_full_name}")
    print(f"✓ Installation ID: {installation_id}")
    print_separator()
    
    # Initialize ClickHouse connection
    print("Initializing ClickHouse connection...")
    try:
        init_ch_engine()
        print("✓ ClickHouse connection initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize ClickHouse: {e}")
        return
    
    print_separator()
    
    # Fetch real tech stack data from GitHub
    print(f"Fetching tech stack data from GitHub for {repository_full_name}...")
    try:
        tech_stack_data = await fetch_github_tech_stack(
            repo_full_name=repository_full_name,
            app_id=app_id,
            private_key_pem=pem_data,
            installation_id=installation_id,
        )
        
        if not tech_stack_data or (not tech_stack_data.get("languages") and not tech_stack_data.get("topics")):
            print("⚠️  No tech stack data retrieved from GitHub")
            print("  This might mean:")
            print("  - Repository doesn't exist or is not accessible")
            print("  - Installation ID doesn't have access to this repository")
            print("  - Repository has no languages or topics")
            return
        
        print("✓ Tech stack data fetched successfully from GitHub")
        
        # Prepare data for storage
        input_data = {
            "repository_full_name": repository_full_name,
            "repository_name": repository_name,
            "installation_id": installation_id,
            "languages": tech_stack_data.get("languages", {}),
            "topics": tech_stack_data.get("topics", []),
            "source": tech_stack_data.get("source", "github"),
        }
        
        print_separator()
        print("Fetched Tech Stack Data from GitHub:")
        print_tech_stack_data("INPUT DATA", input_data)
        print_separator()
        
    except Exception as e:
        print(f"✗ Failed to fetch tech stack data from GitHub: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Get ClickHouse session
    session = get_ch_session_direct()
    
    try:
        # Insert/update tech stack data
        print("Inserting tech stack data into ClickHouse...")
        success = await insert_or_update_tech_stack_ch(
            session=session,
            repository_full_name=input_data["repository_full_name"],
            repository_name=input_data["repository_name"],
            installation_id=input_data["installation_id"],
            languages=input_data["languages"],
            topics=input_data["topics"],
            source=input_data["source"],
        )
        
        if success:
            print("✓ Tech stack data inserted successfully")
        else:
            print("✗ Failed to insert tech stack data")
            return
        
        print_separator()
        
        # Retrieve tech stack data
        print("Retrieving tech stack data from ClickHouse...")
        retrieved_data = await get_tech_stack_ch(
            session=session,
            repository_full_name=input_data["repository_full_name"],
            installation_id=input_data["installation_id"],
        )
        
        if retrieved_data:
            print("✓ Tech stack data retrieved successfully")
            print_separator()
            print("Retrieved Tech Stack Data from ClickHouse:")
            print_tech_stack_data("RETRIEVED DATA", retrieved_data)
            print_separator()
            
            # Verify data matches
            print("Verification:")
            print("-" * 80)
            
            # Check languages
            if retrieved_data.get("languages") == input_data["languages"]:
                print("✓ Languages match")
            else:
                print("✗ Languages do not match")
                print(f"  Expected: {input_data['languages']}")
                print(f"  Got: {retrieved_data.get('languages')}")
            
            # Check topics
            retrieved_topics = set(retrieved_data.get("topics", []))
            expected_topics = set(input_data["topics"])
            if retrieved_topics == expected_topics:
                print("✓ Topics match")
            else:
                print("✗ Topics do not match")
                print(f"  Expected: {sorted(expected_topics)}")
                print(f"  Got: {sorted(retrieved_topics)}")
            
            # Check other fields
            checks = [
                ("repository_full_name", input_data["repository_full_name"]),
                ("repository_name", input_data["repository_name"]),
                ("installation_id", input_data["installation_id"]),
                ("source", input_data["source"]),
            ]
            
            all_match = True
            for field, expected_value in checks:
                actual_value = retrieved_data.get(field)
                if actual_value == expected_value:
                    print(f"✓ {field} matches")
                else:
                    print(f"✗ {field} does not match (expected: {expected_value}, got: {actual_value})")
                    all_match = False
            
            print("-" * 80)
            if all_match and retrieved_data.get("languages") == input_data["languages"] and retrieved_topics == expected_topics:
                print("\n🎉 All data matches! Test passed!")
            else:
                print("\n⚠️  Some data does not match. Please check the output above.")
            
        else:
            print("✗ Failed to retrieve tech stack data")
            print("  Data may not have been inserted correctly")
    
    except Exception as e:
        print(f"✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Close session
        session.close()
        print_separator()
        print("Test completed. ClickHouse session closed.")


if __name__ == "__main__":
    asyncio.run(main())

