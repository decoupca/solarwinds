import inspect
from typing import Union
from logging import NullHandler, getLogger

from solarwinds.exceptions import (
    SWIDNotFound,
    SWObjectPropertyError,
    SWUriNotFound,
)
from solarwinds.config import EXCLUDE_CUSTOM_PROPS
from solarwinds.utils import camel_to_snake, parse_response, sanitize_swdata

log = getLogger(__name__)
log.addHandler(NullHandler())

class Endpoint(object):
    endpoint = None
    uri = None
    exists = False
    _id = None
    _id_attr = None
    _swid_key = None
    _swquery_attrs = None
    _swargs_attrs = None
    _required_swargs_attrs = None
    _swargs = None
    _extra_swargs = None
    _swdata = None
    _changes = None
    _exclude_custom_props = EXCLUDE_CUSTOM_PROPS
    _child_objects = None


    def __init__(self):
        self.uri = self._get_uri()
        self.exists = self._object_exists()
        if self.exists:
            self._get_swdata()
            self._update_attrs()
            #self._init_child_objects()
            #self._update_object_from_children()

    def _get_uri(self, refresh: bool = False) -> Union[str, None]:
        """
        Get object's SWIS URI
        """
        if self._swquery_attrs is None:
            raise SWObjectPropertyError('Missing required property: _swquery_attrs')
        if self.uri is None or refresh is True:
            log.debug("uri is not set or refresh is True, updating...")
            queries = []
            for attr in self._swquery_attrs:
                v = getattr(self, attr)
                if v is not None:
                    k = attr.replace("_", "")
                    queries.append(
                        f"SELECT Uri as uri FROM {self.endpoint} WHERE {k} = '{v}'"
                    )
            if queries:
                query_lines = "\n".join(queries)
                log.debug(f"built SWQL queries:\n{query_lines}")
                for query in queries:
                    result = self.query(query)
                    if result:
                        uri = result['uri']
                        log.debug(f"found uri: {uri}")
                        return uri
                return None
            else:
                key_attrs = ", ".join(self._swquery_attrs)
                raise SWObjectPropertyError(
                    f"At least one of these attributes must be set: {key_attrs}"
                )
        else:
            log.debug("self.uri is set and refresh is False, doing nothing")

    def _object_exists(self, refresh: bool = False) -> bool:
        """
        Whether or not object exists
        """
        return bool(self.uri)

    def _get_swdata(self, refresh: bool = False, data: str = "both") -> None:
        """Caches solarwinds data about an object"""
        if self._swdata is None or refresh is True:
            swdata = {"properties": None, "custom_properties": None}
            log.debug("getting object data from solarwinds...")
            if data == "both" or data == "properties":
                swdata["properties"] = sanitize_swdata(self.swis.read(self.uri))
            if data == "both" or data == "custom_properties":
                if hasattr(self, "custom_properties"):
                    swdata["custom_properties"] = sanitize_swdata(
                        self.swis.read(f"{self.uri}/CustomProperties")
                    )
            if (
                swdata.get("properties") is not None
                or swdata.get("custom_properties") is not None
            ):
                self._swdata = swdata
        else:
            log.debug(
                "_swdata is already set and refresh is False, doing nothing"
            )

    def _update_attrs(self, attr_updates: dict = None, overwrite: bool = False) -> None:
        """
        Updates object attributes from dict
        """
        if attr_updates is None:
            attr_updates = self._get_attr_updates()
        
        cprops_attr_updates = {}
        if 'custom_properties' in attr_updates.keys():
            cprops_attr_updates = attr_updates.pop('custom_properties')
        
        # normal attributes
        for attr, new_v in attr_updates.items():
            v = getattr(self, attr)
            if v is None or overwrite is True:
                setattr(self, attr, new_v)
                log.debug(f"updated self.{attr} = {new_v}")
            else:
                log.debug(
                    f"{attr} already has value '{v}' and overwrite is False, "
                    f"leaving intact"
                )
        # custom properties
        cprops_sw_updates = self._get_cp_updates(overwrite=overwrite)
        self.custom_properties = {**cprops_attr_updates, **cprops_sw_updates} or None


    def _get_cp_updates(self, overwrite: bool = False) -> dict:
        cprops = {}
        if self._swdata is not None:
            if self._swdata.get("custom_properties") is not None:
                if hasattr(self, "custom_properties"):
                    for k, sw_v in self._swdata["custom_properties"].items():
                        if k not in self._exclude_custom_props:
                            v = None if self.custom_properties is None else self.custom_properties.get(k)
                            if v is None or overwrite is True:
                                cprops[k] = sw_v
                                log.debug(f'custom_properties["{k}"] = {sw_v}')
                else:
                    log.warning(
                        f"Object does not have custom_properties attribute, "
                        "but self._swdata has custom properties. Doing nothing, but "
                        "consider revising module to include custom_properties attribute"
                    )
        return cprops

    def _get_sw_attr_values(self):
        return None

    def _init_child_objects(self):
        if self._child_objects is not None:
            log.debug("initializing child objects...")
            for child_class, child_props in self._child_objects.items():

                # initialize child object attribute
                child_attr = child_props["child_attr"]
                if not hasattr(self, child_attr):
                    setattr(self, child_attr, None)
                child_object = getattr(self, child_attr)

                if child_object is None:
                    child_args = {}

                    # some child classes might need args to init.
                    # most should be able to init without any args, but just in case,
                    # here we provide the option.
                    if child_props.get("init_args") is not None:
                        for child_arg, parent_arg in child_props["init_args"].items():
                            parent_value = getattr(self, parent_arg)
                            if parent_value is None:
                                raise SWObjectPropertyError(
                                    f"Can't init child object {child_class}, "
                                    f"parent arg {parent_arg} is None"
                                )
                            else:
                                child_args[child_arg] = parent_value

                    # initialize child object
                    setattr(self, child_attr, child_class(self.swis, **child_args))
                    log.debug(f"initialized child object at {child_attr}")
                else:
                    log.debug("child object already initialized, doing nothing")
        else:
            log.debug(f"no child objects found, doing nothing")

    def _update_child_objects(self):
        """updates child attrs from parent attrs defined in _child_attrs
        and builds child swargs
        """
        if self._child_objects is not None:
            for child_class, child_props in self._child_objects.items():
                child_object = getattr(self, child_props["child_attr"])
                if child_object is not None:
                    for local_attr, child_attr in child_props["attr_map"].items():
                        local_value = getattr(self, local_attr)
                        setattr(child_object, child_attr, local_value)
                        log.debug(
                            f'updated child attribute {child_props["child_attr"]} to "{local_value}" '
                            f"from local attribute {local_attr}"
                        )
                    child_object._build_swargs()
                else:
                    log.warning(
                        f'child object at {child_props["child_attr"]} is None, cannot update'
                    )
        else:
            log.warning("self._child_objects is None, nothing to update")

    def _build_attr_map(self):
        """builds a map of local attributes to solarwinds properties"""
        if self._attr_map is None:
            log.debug("building attribute map...")
            attr_map = {}
            for sw_k, sw_v in self._swdata["properties"].items():
                local_attr = camel_to_snake(sw_k)
                if hasattr(self, local_attr):
                    attr_map[local_attr] = sw_k
                    log.debug(f"added {local_attr} to attribute map")
            if attr_map:
                self._attr_map = attr_map
            else:
                log.warning("found no attributes to map")
        else:
            log.debug("attributes already mapped, doing nothing")

 
    def _update_object_from_children(self, overwrite=False):
        if self._child_objects is not None:
            for child_class, child_props in self._child_objects.items():
                child_object = getattr(self, child_props["child_attr"])
                if child_object is not None:
                    for local_attr, child_attr in child_props["attr_map"].items():
                        child_value = getattr(child_object, child_attr)
                        local_value = getattr(self, local_attr)
                        if local_value != child_value or overwrite is True:
                            setattr(self, local_attr, child_value)
                            log.debug(
                                f"updated local attr {local_attr} = {child_value} from child attr {child_attr}"
                            )

    def _build_swargs(self):
        swargs = {"properties": {}, "custom_properties": {}}
        log.debug("building swargs...")

        # properties
        args = inspect.getfullargspec(self.__init__)[0]
        for arg in args:
            if arg in self._swargs_attrs:
                value = getattr(self, arg)
                # store args without underscores so they match
                # solarwinds argument names
                arg = arg.replace("_", "")
                swargs["properties"][arg] = value
                log.debug(f'_swargs["properties"]["{arg}"] = {value}')

        # extra swargs
        extra_swargs = self._get_extra_swargs()
        if extra_swargs:
            for k, v in extra_swargs.items():
                swargs["properties"][k] = v
                log.debug(f'_swargs["properties"]["{k}"] = {v}')

        # custom properties
        if hasattr(self, "custom_properties"):
            swargs["custom_properties"] = self.custom_properties
            log.debug(f'_swargs["custom_properties"] = {self.custom_properties}')

        # update _swargs
        if swargs["properties"] or swargs["custom_properties"]:
            self._swargs = swargs

        # child objects
        self._update_child_objects()

    def _get_extra_swargs(self):
        # overwrite in subcasses if they have extra swargs
        return {}

    def _diff_properties(self):
        changes = {}
        log.debug("diff'ing properties...")
        for k, sw_v in self._swdata["properties"].items():
            k = k.lower()
            local_v = self._swargs["properties"].get(k)
            if local_v:
                if local_v != sw_v:
                    changes[k] = local_v
                    log.debug(f"property {k} has changed from {sw_v} to {local_v}")
        if changes:
            return changes
        else:
            log.debug("no changes to properties found")

    def _diff_custom_properties(self):
        changes = {}
        log.debug("diff'ing custom properties...")
        if self._swargs["custom_properties"] is not None:
            for k, local_v in self._swargs["custom_properties"].items():
                if k not in self._swdata["custom_properties"].keys():
                    changes[k] = local_v
                sw_v = self._swdata["custom_properties"].get(k)
                if sw_v != local_v:
                    changes[k] = local_v
                    log.debug(
                        f'custom property {k} has changed from "{sw_v}" to "{local_v}"'
                    )
        if changes:
            return changes
        else:
            log.debug("no changes to custom_properties found")

    def _diff_child_objects(self):
        changes = {}
        log.debug("diff'ing child objects...")
        if self._child_objects is not None:
            for child_class, child_props in self._child_objects.items():
                child_object = getattr(self, child_props["child_attr"])
                child_object.diff()
                if child_object._changes is not None:
                    changes[child_object] = child_object._changes
        if changes:
            return changes

    def diff(self):
        changes = {}
        self._build_swargs()
        if self.exists():
            self._get_swdata()
            changes = {
                "properties": self._diff_properties(),
                "custom_properties": self._diff_custom_properties(),
                "child_objects": self._diff_child_objects(),
            }
        else:
            changes = {
                "properties": self._swargs["properties"],
                "custom_properties": self._swargs["custom_properties"],
                "child_objects": self._diff_child_objects(),
            }
        if (
            changes["properties"] is not None
            or changes["custom_properties"] is not None
            or changes["child_objects"] is not None
        ):
            self._changes = changes
            log.debug(f"found changes: {changes}")
        else:
            log.debug("no changes found")

    def _get_id(self):
        if self._swdata is not None:
            object_id = self._swdata["properties"].get(self._swid_key)
            if object_id is not None:
                self.id = object_id
                setattr(self, self._id_attr, object_id)
                log.debug(f"got solarwinds object id {self.id}")
            else:
                raise SWIDNotFound(
                    f'Could not find id value in _swdata["{self._swid_key}"]'
                )
        else:
            log.debug("_swdata is None, can't get id")

    def create(self):
        """Create object"""
        if self.exists():
            log.warning("object exists, can't create")
            return False
        else:
            if self._required_attrs is not None:
                for attr in self._required_attrs:
                    if getattr(self, attr) is None:
                        raise SWObjectPropertyError(
                            f"Missing required attribute: {attr}"
                        )
            self._build_swargs()
            if self._swargs is None:
                raise SWObjectPropertyError("Can't create object without properties.")
            else:
                self.uri = self.swis.create(self.endpoint, **self._swargs["properties"])
                log.debug("created object")
                if self._swargs["custom_properties"]:
                    self.swis.update(
                        f"{self.uri}/CustomProperties",
                        **self._swargs["custom_properties"],
                    )
                    log.debug("added custom properties")
                self._get_swdata()
                self._get_id()
                self._update_object()
                if self._child_objects is not None:
                    # child objects usually (always?) rely on IDs from parent objects
                    # that we don't have until we create the parent object
                    self._update_child_objects()
                    for child_class, child_props in self._child_objects.items():
                        child_object = getattr(self, child_props["child_attr"])
                        # though unlikely, a child object may exist when a parent
                        # object doesn't
                        if child_object.exists():
                            child_object.update()
                        else:
                            child_object.create()
                return True

    def delete(self):
        """Delete object"""
        if self.exists():
            self.swis.delete(self.uri)
            log.debug("deleted object")
            self.uri = None
            return True
        else:
            log.warning("object doesn't exist")
            return False



    def get(self, refresh=False, overwrite=False):
        """Gets object data from solarwinds and updates local object attributes"""
        if self.exists(refresh=refresh):
            log.debug("getting object details...")
            self._get_swdata(refresh=refresh)
            self._get_id()
            self._update_object(overwrite=overwrite)
            self._update_child_objects()
            self._update_object_from_children(overwrite=overwrite)
            self._build_swargs()
        else:
            log.warning("object doesn't exist, nothing to get")

    def query(self, query):
        log.debug(f"executing SWIS query: {query}")
        return parse_response(self.swis.query(query))

    def update(self):
        """Update object in solarwinds with local object's properties"""
        self._build_swargs()
        if self.exists():
            if self._changes is None:
                log.debug("found no changes, running diff()...")
                self.diff()
            if self._changes is not None:
                if self._changes.get("properties") is not None:
                    self.swis.update(self.uri, **self._changes["properties"])
                    log.info(f"updated properties")
                    self._get_swdata(refresh=True, data="properties")
                if self._changes.get("custom_properties") is not None:
                    self.swis.update(
                        f"{self.uri}/CustomProperties",
                        **self._changes["custom_properties"],
                    )
                    log.info(f"updated custom properties")
                    self._get_swdata(refresh=True, data="custom_properties")
                if self._changes.get("child_objects") is not None:
                    log.debug("found changes to child objects")
                    for child_object, changes in self._changes["child_objects"].items():
                        child_props = self._child_objects[child_object.__class__]
                        child_object = getattr(self, child_props["child_attr"])
                        child_object.update()
                    log.info(f"updated child objects")
                self._changes = None
                return True
            else:
                log.warning("found no changes to update, doing nothing")
                return False
        else:
            log.debug("object does not exist, creating...")
            return self.create()