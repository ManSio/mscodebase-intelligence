; Scala tags query — version-matched to tree-sitter-scala 0.26.x

(class_definition
  name: (_) @name
) @definition.class

(trait_definition
  name: (_) @name
) @definition.trait

(object_definition
  name: (_) @name
) @definition.type

(function_definition
  name: (_) @name
) @definition.function

(enum_definition
  name: (_) @name
) @definition.enum
