# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import click
import yaml

from c7n_gcp.client import Session


@click.command()
@click.option(
    '-f', '--output', type=click.File('w'), default='-',
    help="File to store the generated config (default stdout)")
@click.option('-i', '--ignore', multiple=True,
  help="list of folders that won't be added to the config file")
@click.option('-b', '--buid', required=False,  
    help="Business Unit Folder ID")
@click.option('-ap','--appscript', default=False, is_flag=True,
  help="list of app script projects to account files")
def main(output, ignore, appscript, buid):
    """
    Generate a c7n-org gcp projects config file
    """
    client = Session().client('cloudresourcemanager', 'v1', 'projects')

    print("***** Client:", client)


    results = []
    for page in client.execute_paged_query('list', {}):

        print("Page:", page)

        for project in page.get('projects', []):

            print("Projects:", project)

            # Exclude App Script GCP Projects
            if appscript == False:
                if 'sys-' in project['projectId']:
                    continue
                
            if project['lifecycleState'] != 'ACTIVE':
                continue

            if project["parent"]["id"] in ignore:
                continue
            
            if buid and project["parent"]["id"] != buid:
                continue


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