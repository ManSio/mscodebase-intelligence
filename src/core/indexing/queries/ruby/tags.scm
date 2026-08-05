; Ruby tags query

; Classes
(class
  name: (constant) @name
  (#set! "kind" "class")
) @definition.class

; Modules
(module
  name: (constant) @name
  (#set! "kind" "module")
) @definition.type

; Methods
(method
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Singleton methods
(singleton_method
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Methods with arguments
(def
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Singleton class def
(sclass
  name: (constant) @name
) @definition.class

; Calls
(call
  method: (identifier) @name
) @reference.call

(call
  method: (operator) @name
) @reference.call

; Require/load (imports)
(call
  method: (identifier) @_req
  (#eq? @_req "require")
  arguments: (argument_list
    (string) @module
  )
) @definition.import

(call
  method: (identifier) @_req
  (#eq? @_req "load")
  arguments: (argument_list
    (string) @module
  )
) @definition.import

; Variables
(assignment
  left: (identifier) @name
) @definition.variable

(lvasgn
  name: (identifier) @name
) @definition.variable

(ivasgn
  name: (identifier) @name
) @definition.variable

(cvasgn
  name: (identifier) @name
) @definition.variable

(gvasgn
  name: (identifier) @name
) @definition.variable

; Constants
(casgn
  name: (identifier) @name
) @definition.variable