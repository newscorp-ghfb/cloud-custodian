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
    client = resource_manager.Client()

    query_filter = ''
    if buid:
        # Adjust this filter according to the API's requirements and capabilities.
        query_filter = f'parent.id:{buid} parent.type:folder'
    
    projects = client.list_projects(filter=query_filter)
    
    results = []
    for project in projects:

        print("Projects:", project)
        print("******************")

        if project.status != 'ACTIVE':
            continue

        if project.project_id.startswith('sys-') and not appscript:
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