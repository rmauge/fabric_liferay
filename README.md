fabric_liferay
==============

A set of Fabric tasks to deploy a compressed Liferay bundle from a source location to a remote server
I use Hudson as a CI server, but the tasks are general enough to be used with any server since it simply moves
a tar.gz file via ssh.


## Getting Started
An ant task is used to call the Fabric script on the Hudson as the last step of the build but this can also
be called from the command line (which the Ant script does essentially)


```
  <!-- Default values for Fabric deploy -->
	<property name="health.check" value="" />
	<property name="health.check.remote.server" value="" />
	<property name="python.virtualenv.dir" value="/srv/applications/fabric-virtualenv/" />
	<property name="deployment.script.name" value="scripts/fabfile.py" />
  ....
  <target name="fabric-deploy" depends="create-revision-tarball" description="Deploys application using the Fabric deployment tool installed on build server">
		<exec executable="/bin/bash" failonerror="true">
		    <arg line="-c 'source ${python.virtualenv.dir}bin/activate; fab -f ${deployment.script.name}
		  					-H ${deployment.server}
		  					-u ${deployment.username}
		  					debug deploy:bundle_name=${bundle.filename},bundle_extracted_name=${revision.branch}-r${revision.number},do_health_check=${health.check},remote_server=${health.check.remote.server}' "/>
		</exec>
	</target>
```

* bundle_name is the name of the tar.gz file. Ex. liferay01-aws-6034.tgz
* bundle_extracted_name is the name of the exploded directory. Ex. aws-r6034

SSH keys exchange are setup between the servers to allow deploys without using passwords.

## Walkthrough

The high level steps are to take the server offline then deploy and put back online
* By stopping any monitoring tool, then the web server and then the application server.
* Doing a health check
* Bring the server back online by reversing the steps

A symlink is used to point to the new deploy "current" and the old deploy is saved to "previous"
in case you need to roll-back.

The core is the health check which uses an ssh tunnel to determine if the server is ready.
The implementation of that check is left up to you. We have a status page that checks all essential components
and displays an "UP" is they all pass. I am using a regex to check for that indicator.


It should be easy enough to apply this template to any application.

## License

This is licensed under the MIT license and is included with the source.
