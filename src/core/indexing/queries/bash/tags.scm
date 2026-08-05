; Bash tags query

; Functions
(function_definition
  name: (function_name) @name
  (#set! "kind" "function")
) @definition.function

; Calls
(command
  name: (command_name) @name
) @reference.call

; Source/Import
(source_statement
  (word) @module
) @definition.import

; Variables
(variable_assignment
  name: (variable_name) @name
) @definition.variable

(variable_assignment
  name: (array_variable
    name: (variable_name) @name
  )
) @definition.variable