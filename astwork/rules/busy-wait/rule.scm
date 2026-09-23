; rules/busy-wait/rule.scm
((while_statement
    condition: (comparison_operator
                 (call
                   function: (attribute
                               object: (identifier) @_module
                               attribute: (identifier) @_func)))
    body: (block
            [(pass_statement) (continue_statement)]))

    @busy_wait_loop)
