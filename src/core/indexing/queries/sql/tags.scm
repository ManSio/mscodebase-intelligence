; SQL tags query (tree-sitter-sql)

; Tables
(create_table_statement
  table: (object_reference
    name: (identifier) @name
  )
  (#set! "kind" "table")
) @definition.type

; Views
(create_view_statement
  name: (object_reference
    name: (identifier) @name
  )
  (#set! "kind" "view")
) @definition.type

; Functions
(create_function_statement
  name: (function_name
    name: (identifier) @name
  )
  (#set! "kind" "function")
) @definition.function

; Procedures
(create_procedure_statement
  name: (procedure_name
    name: (identifier) @name
  )
  (#set! "kind" "procedure")
) @definition.function

; Indexes
(create_index_statement
  name: (index_name
    name: (identifier) @name
  )
  (#set! "kind" "index")
) @definition.type

; Calls (function calls in queries)
(function_call
  name: (identifier) @name
) @reference.call

; Table references
(object_reference
  name: (identifier) @name
) @reference.type

; Column definitions
(column_definition
  name: (column_name
    name: (identifier) @name
  )
) @definition.variable