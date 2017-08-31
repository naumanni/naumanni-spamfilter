/* eslint-disable no-unused-vars */
import {Map} from 'immutable'
import React from 'react'
import Toggle from 'react-toggle'
import classNames from 'classnames'
import {intlShape, FormattedMessage as _FM} from 'react-intl'


const hackTimelineStatus = (api, uiComponents) => {
  const {IconFont} = uiComponents

  uiComponents.TimelineStatus = class SpamFilterTimelineStatus extends uiComponents.TimelineStatus {
    static contextTypes = {
      intl: intlShape,
    }

    /**
     * @override
     */
    shouldComponentUpdate(nextProps, nextState) {
      if(nextProps.isSpamFilterActive !== this.props.isSpamFilterActive)
        return true

      return super.shouldComponentUpdate(nextProps, nextState)
    }

    shouldHideContent() {
      const {status} = this.props
      const {isSpamOpen, isSpamReported} = this.state
      const score = status.getExtended('spamfilter')

      // レポート済Spamはもう表示しない
      if(isSpamReported)
        return true

      if(!score) {
        return false
      }

      if(!(score.get('is_spam') && !isSpamOpen)) {
        return false
      }

      return true
    }

    renderBody() {
      if(!this.props.isSpamFilterActive)
        return super.renderBody()
      if(!this.shouldHideContent())
        return super.renderBody()

      // hide content
      const {isSpamReported} = this.state
      return (
        <div className="spamfilter-hideContent">
          <span className="spamFilter-attentionMessage">
            <IconFont iconName="attention" />
            <_FM id="spamfilter.label.attention" />
          </span>

          {!isSpamReported &&
          <button
            onClick={this.onClickOpenSpam.bind(this)}
            className="button button--mini button--warning"><_FM id="spamfilter.label.show_toot" /></button>
          }
        </div>
      )
    }

    renderMedia() {
      if(!this.props.isSpamFilterActive)
        return super.renderMedia()
      if(!this.shouldHideContent())
        return super.renderMedia()
    }

    renderActions() {
      if(!this.props.isSpamFilterActive)
        return super.renderActions()
      if(!this.shouldHideContent())
        return super.renderActions()
    }

    renderActionButtons() {
      const {formatMessage: _} = this.context.intl
      const {status} = this.props
      const {isSpamReported} = this.state
      const buttons = super.renderActionButtons()
      const score = status.getExtended('spamfilter')
      const badScore = score ? score.get('bad_score').toFixed(4) : '---'
      const goodScore = score ? score.get('good_score').toFixed(4) : '---'

      /// 最後のdotの1個前に入れる
      buttons.splice(buttons.length - 1, 0,
        <button
          key="spamButton"
          className=""
          disabled={isSpamReported ? true : false}
          alt={_({id: 'spamfilter.label.report'})}
          title={`${_({id: 'spamfilter.label.report'})}\n${badScore} / ${goodScore}`}
          onClick={this.onClickReportAsSpam.bind(this)}>
          <IconFont iconName="cancel" />
        </button>
      )

      return buttons
    }

    onClickOpenSpam() {
      this.setState({isSpamOpen: true})
    }

    /**
     * 当該トゥートをSpamとして報告する
     */
    onClickReportAsSpam() {
      const {account, status} = this.props
      this.setState({isSpamReported: true})

      // 投げっぱなし
      api.makePluginRequest('POST', 'spamfilter', '/report')
        .send({
          status: status.toJSON(),
          account: account.toJSON(),
        })
        .end()
    }
  }
}

const hackColumnHeaderMenu = (uiComponents) => {
  uiComponents.ColumnHeaderMenu =
    class SpamFilterColumnHeaderMenu extends uiComponents.ColumnHeaderMenu {

      /**
       * @override
       */
      render() {
        const {
          children, isCollapsed,
          isSpamFilterActive, onToggleSpamFilter, onClickClose,
        } = this.props

        return (
          <div className={classNames(
            'column-menuContent',
            {'collapsed': isCollapsed}
          )} ref="container">
            {children}
            <div className="menu-item menu-item--toggle">
              <Toggle
                checked={isSpamFilterActive}
                onChange={onToggleSpamFilter} />
              <label htmlFor={`spam-visibility`}><_FM id="spamfilter.column.menu.filter_spams" /></label>
            </div>
            <div className="menu-item--default" onClick={onClickClose}>
              <_FM id="column.menu.close" />
            </div>
          </div>
        )
      }
    }
}

const hackTimelineColumn = (uiColumns, {ColumnHeaderMenu: SpamFilterColumnHeaderMenu}) => {
  const TIMELINE_FILTER_SPAMFILTER = 'timeline_filter_spamfilter'

  uiColumns.timeline = 
    class SpamFilterTimelineColumn extends uiColumns.timeline {

      constructor(...args) {
        super(...args)
        this.state = {
          ...this.state,
          isSpamFilterActive: localStorage.getItem(this.storageKeyForFilter(TIMELINE_FILTER_SPAMFILTER))
            ? JSON.parse(localStorage.getItem(this.storageKeyForFilter(TIMELINE_FILTER_SPAMFILTER)))
            : false,
        }
      }

      /**
       * @override
       */
      renderMenuContent() {
        return (
          <SpamFilterColumnHeaderMenu
            isCollapsed={!this.state.isMenuVisible}
            isSpamFilterActive={this.state.isSpamFilterActive}
            onToggleSpamFilter={this.onToggleSpamFilter.bind(this)}
            onClickClose={this.props.onClose}
          >
            {this.renderFilterMenus()}
          </SpamFilterColumnHeaderMenu>
        )
      }

      /**
       * @override
       */
      propsForPagingContent() {
        const {isSpamFilterActive} = this.state

        return {
          ...super.propsForPagingContent(),
          options: {
            isSpamFilterActive,
          },
        }
      }

      // cb

      onClickMenuButton(e) {
        e.stopPropagation()
        this.setState({isMenuVisible: !this.state.isMenuVisible})
      }

      onToggleSpamFilter() {
        const newValue = !this.state.isSpamFilterActive

        this.setState({isSpamFilterActive: newValue})

        localStorage.setItem(this.storageKeyForFilter(TIMELINE_FILTER_SPAMFILTER), newValue)
      }
    }
}

export default function initialize({api, uiColumns, uiComponents}) {
  hackTimelineStatus(api, uiComponents)
  hackColumnHeaderMenu(uiComponents)
  hackTimelineColumn(uiColumns, uiComponents)
}
