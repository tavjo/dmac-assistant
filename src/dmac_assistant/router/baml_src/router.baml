class TaskFamily {
  name             string
  description      string
  example_queries  string[]
}

class RouteCapability {
  route_name     string
  description    string
  tools          string[]
  best_for       string?
  not_for        string?
  task_families  TaskFamily[]
}

class RouterInput {
  user_query  string
  routes      RouteCapability[]
}

enum Route {
  NextseekQuery @alias("nextseek_query")
  ContainerCC   @alias("container_cc")
}

enum ModelClass {
  Sonnet @alias("sonnet")
  Haiku  @alias("haiku")
  Opus   @alias("opus")
}

class RouterDecision {
  route        Route
  model_class  ModelClass?
  reasoning    string
}

function RouteQuery(input: RouterInput) -> RouterDecision {
  client GCPReasoner
  prompt #"
    You route a user query to one of the available execution routes for the
    DMAC research assistant. Use the route's declared capabilities to decide.

    {% for route in input.routes %}
    ## {{ route.route_name }}
    {{ route.description }}

    Tools / plugins / skills: {{ route.tools|join(", ") }}
    {% if route.best_for %}Best for: {{ route.best_for }}{% endif %}
    {% if route.not_for %}Avoid for: {{ route.not_for }}{% endif %}

    Task families:
    {% for tf in route.task_families %}
    - {{ tf.name }} — {{ tf.description }}
      Example queries:
      {% for q in tf.example_queries %}
      * "{{ q }}"
      {% endfor %}
    {% endfor %}
    {% endfor %}

    User query: {{ input.user_query }}

    If you select `container_cc`, also pick a model class:
      - haiku  : trivial Q&A / classification / short factual lookups
      - sonnet : default general-purpose
      - opus   : hard reasoning, multi-step planning, large refactors
    If you select `nextseek_query`, omit model_class.

    {{ ctx.output_format }}
  "#
}
