# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import click
import yaml

from c7n_gcp.client import Session


@click.command()
@click.option('-f', '--output', type=click.File('w'), default='-',
    help="File to store the generated config (default stdout)")
@click.option('-e', '--exclude', required=False, 
  help="List of Project Numbers to be excluded from the Projects File")
@click.option('-b', '--buid', required=False,  
    help="Business Unit Folder ID")
# @click.option('-ap','--appscript', default=False, is_flag=True,
#   help="list of app script projects to account files")
# def main(output, exclude, buid, appscript):
def main(output, exclude, buid):

    """
    Generate a c7n-org gcp projects config file
    """
    client = Session().client('cloudresourcemanager', 'v1', 'projects')

    results = []
    for page in client.execute_paged_query('list', {}):

        # print("Page:", page)
        print("BUID:", buid)
        print("Exclude:", exclude)



        for project in page.get('projects', []):

            if buid and project["parent"]["id"] != buid:
                continue

            # # Exclude App Script GCP Projects
            # if appscript == False:
            #     if 'sys-' in project['projectId']:
            #         continue
                
            if project['lifecycleState'] != 'ACTIVE' or project['projectNumber'] in exclude:
                continue

            print("Projects:", project)
            print("Project Name:", project['name'])
            print("************************************* - Toyota Tacoma Rocks")

            project_info = {
                'project_id': project['projectId'],
                'project_number': project['projectNumber'],
                'name': project['name'],
            }

            if 'labels' in project:
                project_info['tags'] = [
                    '%s:%s' % (k, v) for k, v in project.get('labels', {}).items()]
                project_info['vars'] = {k: v for k, v in project.get('labels', {}).items()}
            results.append(project_info)

    output.write(
        yaml.safe_dump({'projects': results}, default_flow_style=False))


if __name__ == '__main__':
    main()