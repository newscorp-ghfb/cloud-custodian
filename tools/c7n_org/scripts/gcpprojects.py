# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from c7n_gcp.client import Session
import click
import yaml

@click.command()
@click.option(
    "-f",
    "--output",
    type=click.File("w"),
    default="-",
    help="File to store the generated config (default stdout)",
)
@click.option(
    "-e",
    "--exclude",
    multiple=True,
    help="List of folders that won't be added to the config file",
)
@click.option(
    "-b",
    "--buid",
    required=False,
    multiple=True,
    help="List of folder IDs that will be added to the config file",
)
@click.option(
    "-ap",
    "--appscript",
    default=False,
    is_flag=True,
    help="Exclude App Script projects from the account files",
)
def main(output, exclude, appscript, buid):
    """
    Generate a c7n-org GCP projects config file.
    """
    session = Session()
    client = session.client("cloudresourcemanager", "v1", "projects")
    folder_client = session.client("cloudresourcemanager", "v2", "folders")

    # Helper function to retrieve all subfolders for each buid
    def get_all_subfolders(folder_id):
        subfolders = set()
        request = folder_client.execute_query("list", {"parent": f"folders/{folder_id}"})
        for folder in request.get("folders", []):
            subfolders.add(folder["name"].split("/")[-1])
            subfolders.update(get_all_subfolders(folder["name"].split("/")[-1)))  # Recursive call
        return subfolders

    # Check if buid is empty; if so, assume flat structure and set organization ID
    if not buid:
        print("No BUID specified; assuming flat organization. Listing all projects under organization.")
        organization_id = "organizations/161588151302"  # Sandbox organization ID
        all_folders = set()
    else:
        # Gather all folders and subfolders for hierarchical structure
        all_folders = set(buid)
        for folder_id in buid:
            all_folders.update(get_all_subfolders(folder_id))

    results = []
    for page in client.execute_paged_query("list", {}):
        for project in page.get("projects", []):
            # Exclude App Script projects if the flag is set
            if not appscript and "sys-" in project["projectId"]:
                continue

            # Exclude projects in inactive states or those in excluded folders
            if project["lifecycleState"] != "ACTIVE" or project["projectNumber"] in exclude:
                continue

            # Determine if project is under specified folders or directly under organization
            if (not buid and project["parent"].get("type") == "organization" and project["parent"].get("id") == organization_id) or \
               (buid and project["parent"].get("type") == "folder" and project["parent"].get("id") in all_folders):
                # Collect project details
                project_info = {
                    "project_id": project["projectId"],
                    "project_number": project["projectNumber"],
                    "name": project["name"],
                }

                # Include labels if they exist
                if "labels" in project:
                    project_info["tags"] = [
                        f"{k}:{v}" for k, v in project.get("labels", {}).items()
                    ]
                    project_info["vars"] = {
                        k: v for k, v in project.get("labels", {}).items()
                    }
                
                results.append(project_info)

    # Output project information to YAML
    output.write(yaml.safe_dump({"projects": results}, default_flow_style=False))

if __name__ == "__main__":
    main()
