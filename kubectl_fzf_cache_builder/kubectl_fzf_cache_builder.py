#!env python2
import argparse
from kubernetes import client, config, watch
from kubernetes.config import kube_config
import logging
import os.path
import multiprocessing
import signal
import subprocess
import time
from . import resource
import yaml


log = logging.getLogger('dd.' + __name__)

watches = []
exiting = False


def is_expired(user):
    if 'auth-provider' not in user:
        return False
    provider = user['auth-provider']
    if 'config' not in provider:
        return False
    if 'expiry' not in provider['config']:
        return False
    return kube_config._is_expired(provider['config']['expiry'])


def get_kubernetes_config(cluster, refresh_command):
    res = None

    if refresh_command:
        filename = os.path.expanduser(kube_config.KUBE_CONFIG_DEFAULT_LOCATION)
        with open(filename) as f:
            loader = kube_config.KubeConfigLoader(
                config_dict=yaml.load(f),
                config_base_path=os.path.abspath(os.path.dirname(filename)))
            if is_expired(loader._user):
                subprocess.call([refresh_command, cluster])

    res = config.new_client_from_config(context=cluster)
    return res


class ResourceWatcher(object):

    def __init__(self, cluster, namespace, args):
        self.cluster = cluster
        self.namespace = namespace
        kubernetes_config = get_kubernetes_config(cluster, args.refresh_command)
        self.v1 = client.CoreV1Api(api_client=kubernetes_config)
        self.apps_v1 = client.AppsV1Api(api_client=kubernetes_config)
        self.extensions_v1beta1 = client.ExtensionsV1beta1Api(api_client=kubernetes_config)
        self.poll_time = args.poll_time
        self.kube_kwargs = {'_request_timeout': 600}
        if args.selector:
            self.kube_kwargs['label_selector'] = args.selector
        if self.namespace != 'all':
            self.kube_kwargs['namespace'] = self.namespace

    def write_resource_to_file(self, resource, resources, truncate_file, f):
        if truncate_file:
            log.debug('Truncating file {}'.format(resource))
            f.seek(0)
            f.truncate()
            f.writelines(['{}\n'.format(r) for r in resources])
        else:
            f.write('{}\n'.format(str(resource)))
        f.flush()

    def write_resources_to_file(self, resources, f):
        f.writelines(['{}\n'.format(r) for r in resources])
        f.flush()

    def process_resource(self, resource, resources, dest):
        do_truncate = False
        if resource.is_deleted and resource in resources:
            log.debug('Removing resource {}'.format(resource))
            resources.remove(resource)
            do_truncate = True
        else:
            if resource in resources:
                log.debug('Updating resource {}'.format(resource))
                do_truncate = True
                resources.remove(resource)
            resources.add(resource)
        self.write_resource_to_file(resource, resources, do_truncate, dest)

    def _get_resource_kwargs(self, Resource):
        kwargs = self.kube_kwargs
        if not Resource._has_namespace():
            kwargs = dict(self.kube_kwargs)
            kwargs.pop('namespace', None)
        return kwargs

    def watch_resource(self, func, ResourceCls):
        dest_file=ResourceCls._dest_file()
        log.info('Watching {} on namespace {}, writing results in {}'.format(
            ResourceCls.__name__, self.namespace, dest_file))
        w = watch.Watch()
        watches.append(w)
        resources = set()
        with open(dest_file, 'w') as dest:
            kwargs = self._get_resource_kwargs(ResourceCls)
            for resp in w.stream(func, **kwargs):
                resource = ResourceCls(resp['object'])
                self.process_resource(resource, resources, dest)
        log.info('{} watcher exiting'.format(ResourceCls.__name__))

    def poll_resource(self, func, ResourceCls):
        dest_file=ResourceCls._dest_file()
        log.info('Poll {} on namespace {}, writing results in {}'.format(
            ResourceCls.__name__, self.namespace, dest_file))
        kwargs = self._get_resource_kwargs(ResourceCls)
        while exiting is False:
            resp = func(**kwargs)
            resources = [ResourceCls(item) for item in resp.items]
            with open(dest_file, 'w') as dest:
                self.write_resources_to_file(resources, dest)
            time.sleep(self.poll_time)
        log.info('{} poll exiting {}'.format(ResourceCls.__name__, exiting))

    def watch_pods(self):
        func = self.v1.list_namespaced_pod
        if self.namespace == 'all':
            func = self.v1.list_pod_for_all_namespaces
        self.watch_resource(func, resource.Pod)

    def watch_services(self):
        func = self.v1.list_namespaced_service
        if self.namespace == 'all':
            func = self.v1.list_service_for_all_namespaces
        self.watch_resource(func, resource.Service)

    def watch_nodes(self):
        self.poll_resource(self.v1.list_node, resource.Node)

    def watch_replicaset(self):
        func = self.apps_v1.list_namespaced_replica_set
        if self.namespace == 'all':
            func = self.apps_v1.list_replica_set_for_all_namespaces
        self.watch_resource(func, resource.ReplicaSet)

    def watch_configmap(self):
        func = self.v1.list_namespaced_config_map
        if self.namespace == 'all':
            func = self.v1.list_config_map_for_all_namespaces
        self.watch_resource(func, resource.ConfigMap)

    def watch_statefulset(self):
        func = self.apps_v1.list_namespaced_stateful_set
        if self.namespace == 'all':
            func = self.apps_v1.list_stateful_set_for_all_namespaces
        self.watch_resource(func, resource.StatefulSet)

    def watch_deployments(self):
        func = self.extensions_v1beta1.list_namespaced_deployment
        if self.namespace == 'all':
            func = self.extensions_v1beta1.list_deployment_for_all_namespaces
        self.watch_resource(func, resource.Deployment)


def parse_args():
    parser = argparse.ArgumentParser(description='Watch kube resources and keep a local cache up to date.')
    parser.add_argument('--dir', '-d', dest='dir', type=str, help='cache dir location. Default to KUBECTL_FZF_CACHE env var', default=os.environ.get('KUBECTL_FZF_CACHE', None))
    parser.add_argument("--selector", "-l", dest='selector', type=str, help='Resource selector to use', default=None)
    parser.add_argument("--poll-time", dest='poll_time', type=int, help='Time between two list requests for polled resources', default=300)
    parser.add_argument("--namespace", "-n", dest='namespace', type=str, help='Namespace to filter. Default to current namespace. all for no filter', default=None)
    parser.add_argument("--refresh-command", dest='refresh_command', type=str, help='Command to launch when the token is expired', default=None)
    parser.add_argument("--verbose", "-v", dest='verbose', action='store_true')
    return parser.parse_args()


def start_watches(cluster, namespace, args):
    processes = []
    resource_watcher = ResourceWatcher(cluster, namespace, args)
    for f in [resource_watcher.watch_pods, resource_watcher.watch_deployments,
              resource_watcher.watch_services, resource_watcher.watch_nodes,
              resource_watcher.watch_statefulset, resource_watcher.watch_replicaset,
              resource_watcher.watch_configmap]:
        p = multiprocessing.Process(target=f)
        p.daemon = True
        p.start()
        processes.append(p)
    return processes


def wait_loop(processes, cluster, namespace):
    while exiting is False:
        for p in processes:
            p.join(1)
            if not p.is_alive():
                log.info('A process is dead, exiting wait loop')
                return
        new_cluster, new_namespace = get_current_context()
        if cluster != new_cluster:
            log.info('Watched cluster {} != {}'.format(cluster, new_cluster))
            return
        if namespace != new_namespace:
            log.info('Watched namespace {} != {}'.format(namespace, new_namespace))
            return


def get_current_context():
    context = config.list_kube_config_contexts()[1]['context']
    cluster = context['cluster']
    namespace = context['namespace']
    return cluster, namespace


def main():
    args = parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format='%(message)s')

    if not os.path.exists(args.dir):
        os.makedirs(args.dir)

    while exiting is False:
        cluster, namespace = get_current_context()
        if args.namespace is not None:
            namespace = args.namespace
        processes = start_watches(cluster, namespace, args)
        wait_loop(processes, cluster, namespace)
        for p in processes:
            log.warn('Terminating {}'.format(p))
            p.terminate()
            p.join(1)

    log.warn('Exiting')


def stop_watches():
    log.warn('Stopping {} watches'.format(len(watches)))
    for w in watches:
        w.stop()
    del watches[:]


def signal_handler(signal, frame):
    log.warn('Signal received, closing watches')
    stop_watches()
    global exiting
    exiting = True


if __name__ == "__main__":
    main()
