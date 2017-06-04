import {Map} from 'immutable'
import React from 'react'


export default function initialize({uiComponents}) {
  uiComponents.TimelineStatus = class ExtendedTimelineStatus extends uiComponents.TimelineStatus {
    renderBody() {
      const {status} = this.props
      const {isSpamOpen} = this.state
      const score = status.getExtended('spamfilter')

      if(!score || !Map.isMap(score)) {
        return super.renderBody()
      }

      const spamScoreNode = <SpamScore
        spamScore={score.get('spam_score')}
        notSpamScore={score.get('not_spam_score')}
        isSpam={score.get('is_spam')}
      />

      if(score.get('is_spam') && !isSpamOpen) {
        // hide content
        return (
          <div className="spamfilter-hideContent">
            {spamScoreNode}
          </div>
        )
      } else {
        // open content
        return (
          <div className="">
            {super.renderBody()}
            {spamScoreNode}
          </div>
        )
      }
    }

    renderMedia() {
      const {status} = this.props
      const {isSpamOpen} = this.state
      const score = status.getExtended('spamfilter')

      if(!score || !Map.isMap(score)) {
        return super.renderMedia()
      }

      if(score.get('is_spam') && !isSpamOpen) {
        // hide content
        return null
      } else {
        // open content
        return super.renderMedia()
      }
    }
  }
}


class SpamScore extends React.Component {
  render() {
    const {spamScore, notSpamScore, isSpam} = this.props
    return (
      <div className={`spamfilter-spamScore ${isSpam ? 'is-spam' : 'is-not-spam'}`}>
        <span>spamScore: {spamScore.toFixed(4)}</span>
        <span>notSpamScore: {notSpamScore.toFixed(4)}</span>
      </div>
    )
  }
}
