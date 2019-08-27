#!/usr/bin/env python3
import sys
import os
import logging
import json

# 3rd party
from jinja2 import Template
import zlib

sys.path.append(os.path.dirname(__file__))
logger = logging.getLogger('rp')

# internal
import log

RPC_TEMPLATE = """
// This file is autogenerated. Manual changes will be lost.
#pragma once

#include "rpc/types.h"
#include "rpc/netbuf.h"
#include "rpc/parse_utils.h"
#include "rpc/client.h"
#include "rpc/service.h"
#include "seastarx.h"

// extra includes
{%- for include in includes %}
#include "{{include}}"
{%- endfor %}

#include <seastar/core/reactor.hh>
#include <seastar/core/scheduling.hh>

#include <functional>
#include <tuple>

namespace {{namespace}} {

class {{service_name}}_service : public rpc::service {
public:
    class client;

    {{service_name}}_service(scheduling_group& sc, smp_service_group& ssg)
       : _sc(std::ref(sc)), _ssg(std::ref(ssg)) {}

    {{service_name}}_service({{service_name}}_service&& o) noexcept
      : _sc(std::move(o._sc)), _ssg(std::move(o._ssg)), _methods(std::move(o._methods)) {}

    {{service_name}}_service& operator=({{service_name}}_service&& o) noexcept {
       if(this != &o){
          this->~{{service_name}}_service();
          new (this) {{service_name}}_service(std::move(o));
       }
       return *this;
    }

    virtual ~{{service_name}}_service() noexcept = default;

    scheduling_group& get_scheduling_group() override {
       return _sc.get();
    }

    smp_service_group& get_smp_service_group() override {
       return _ssg.get();
    }

    rpc::method* method_from_id(uint32_t idx) final {
       switch(idx) {
       {%- for method in methods %}
         case {{method.id}}: return &_methods[{{loop.index - 1}}];
       {%- endfor %}
         default: return nullptr;
       }
    }
    {%- for method in methods %}
    /// \\brief {{method.input_type}} -> {{method.output_type}}
    virtual future<rpc::netbuf>
    raw_{{method.name}}(input_stream<char>& in, rpc::streaming_context& ctx) {
      auto fapply = execution_helper<{{method.input_type}}, {{method.output_type}}>();
      return fapply.exec(in, ctx, {{method.id}}, [this](
          {{method.input_type}} t, rpc::streaming_context& ctx) -> future<{{method.output_type}}> {
          return {{method.name}}(std::move(t), ctx);
      });
    }
    virtual future<{{method.output_type}}>
    {{method.name}}({{method.input_type}}, rpc::streaming_context&) {
       throw std::runtime_error("unimplemented method");
    }
    {%- endfor %}
private:
    std::reference_wrapper<scheduling_group> _sc;
    std::reference_wrapper<smp_service_group> _ssg;
    std::array<rpc::method, {{methods|length}}> _methods{%raw %}{{{% endraw %}
      {%- for method in methods %}
      rpc::method([this] (input_stream<char>& in, rpc::streaming_context& ctx) {
         return raw_{{method.name}}(in, ctx);
      }){{ "," if not loop.last }}
      {%- endfor %}
    {% raw %}}}{% endraw %};
};
class {{service_name}}_service::client : public rpc::client {
public:
    client(rpc::client_configuration c)
      : rpc::client(std::move(c)) {
    }
    {%- for method in methods %}
    virtual inline future<rpc::client_context<{{method.output_type}}>>
    {{method.name}}({{method.input_type}} r) {
       return send_typed<{{method.input_type}}, {{method.output_type}}>(std::move(r), {{method.id}});
    }
    {%- endfor %}
};

}

"""


def _read_file(name):
    with open(name, 'r') as f:
        return json.load(f)


def _enrich_methods(service):
    logger.info(service)

    service["id"] = zlib.crc32(
        bytes("%s:%s" % (service["namespace"], service["service_name"]),
              "utf-8"))

    def _xor_id(m):
        mid = ("%s:" % service["namespace"]).join(
            [m["name"], m["input_type"], m["output_type"]])
        return service["id"] ^ zlib.crc32(bytes(mid, 'utf-8'))

    for m in service["methods"]:
        m["id"] = _xor_id(m)

    return service


def _codegen(service, out):
    logger.info(service)
    tpl = Template(RPC_TEMPLATE)
    with open(out, 'w') as f:
        f.write(tpl.render(service))


def main():
    import argparse

    def generate_options():
        parser = argparse.ArgumentParser(description='service codegenerator')
        parser.add_argument(
            '--log',
            type=str,
            default='INFO',
            help='info,debug, type log levels. i.e: --log=debug')
        parser.add_argument('--service_file',
                            type=str,
                            help='input file in .json format for the codegen')
        parser.add_argument('--output_file',
                            type=str,
                            default='/dev/stderr',
                            help='output header file for the codegen')
        return parser

    parser = generate_options()
    options, program_options = parser.parse_known_args()
    log.set_logger_for_main(getattr(logging, options.log.upper()))
    logger.info("%s" % options)
    _codegen(_enrich_methods(_read_file(options.service_file)),
             options.output_file)


if __name__ == '__main__':
    main()